"""Thin async wrappers over the Stripe API.

MerchantStripe reads a merchant's own Stripe account, either with the restricted key
they gave us or, when they connected with one click (Connect OAuth), with Kickrail's
key acting as their account. PlatformStripe is Kickrail's account: Connect Express accounts for
affiliates, payout funding, transfers. Tests swap both for fakes.
"""

from datetime import UTC, datetime
from typing import Protocol

import stripe

from ..config import get_settings
from ..crypto import decrypt
from ..domain.commission import Line

MERCHANT_EVENTS = [
    "checkout.session.completed",
    "customer.created",
    "customer.updated",
    "invoice.paid",
    "charge.refunded",
    "charge.dispute.created",
]


def _client(key: str) -> stripe.StripeClient:
    return stripe.StripeClient(key, http_client=stripe.HTTPXClient(allow_sync_methods=False))


class MerchantApi(Protocol):
    async def payment_intent_for_invoice(self, invoice_id: str) -> str | None: ...
    async def invoice_for_payment_intent(self, payment_intent_id: str) -> str | None: ...
    async def create_promotion_code(self, coupon_id: str, code: str, affiliate_id: str) -> str: ...


class MerchantStripe:
    def __init__(self, restricted_key: str, account: str | None = None):
        self.c = stripe.StripeClient(restricted_key, stripe_account=account, http_client=stripe.HTTPXClient(allow_sync_methods=False))

    @classmethod
    def for_merchant(cls, merchant: dict) -> "MerchantStripe":
        s = merchant["stripe"]
        if s.get("oauth"):
            return cls(get_settings().oauth_key, s["account_id"])
        return cls(decrypt(s["key_enc"]))

    @classmethod
    def for_account(cls, account_id: str) -> "MerchantStripe":
        return cls(get_settings().oauth_key, account_id)

    async def customer_created(self, customer_id: str) -> datetime | None:
        c = await self.c.v1.customers.retrieve_async(customer_id)
        return datetime.fromtimestamp(c.created, UTC) if getattr(c, "created", None) else None

    async def account(self) -> dict:
        acct = await self.c.v1.accounts.retrieve_current_async()
        profile = acct.get("business_profile") or {}
        settings = acct.get("settings") or {}
        # The dashboard name is what the merchant sees in Stripe; sandboxes report "Sandbox" as the business name.
        name = (settings.get("dashboard") or {}).get("display_name") or profile.get("name") or acct.id
        return {"id": acct.id, "name": name}

    async def create_webhook(self, url: str) -> tuple[str, str]:
        ep = await self.c.v1.webhook_endpoints.create_async(
            {"url": url, "enabled_events": MERCHANT_EVENTS, "description": "Kickrail affiliate tracking"}  # type: ignore[typeddict-item]
        )
        return ep.id, ep.secret or ""

    async def delete_webhook(self, endpoint_id: str) -> None:
        await self.c.v1.webhook_endpoints.delete_async(endpoint_id)

    async def payment_intent_for_invoice(self, invoice_id: str) -> str | None:
        page = await self.c.v1.invoice_payments.list_async({"invoice": invoice_id, "status": "paid", "limit": 1})
        for p in page.data:
            return (p.payment or {}).get("payment_intent")
        return None

    async def invoice_for_payment_intent(self, payment_intent_id: str) -> str | None:
        page = await self.c.v1.invoice_payments.list_async(
            {"payment": {"type": "payment_intent", "payment_intent": payment_intent_id}, "limit": 1}
        )
        for p in page.data:
            return p.invoice if isinstance(p.invoice, str) else p.invoice.id
        return None

    async def create_promotion_code(self, coupon_id: str, code: str, affiliate_id: str) -> str:
        pc = await self.c.v1.promotion_codes.create_async(
            {"promotion": {"type": "coupon", "coupon": coupon_id}, "code": code, "metadata": {"kr_affiliate": affiliate_id}}
        )
        return pc.id

    async def checkout_lines(self, session_id: str):
        page = await self.c.v1.checkout.sessions.line_items.list_async(session_id, {"limit": 100})
        return [Line(li.amount_subtotal or 0, li.price.product if li.price and isinstance(li.price.product, str) else None, li.price.id if li.price else None) for li in page.data]

    async def list_coupons(self) -> list[dict]:
        page = await self.c.v1.coupons.list_async({"limit": 50})
        return [{"id": c.id, "name": c.name or c.id, "percent_off": c.percent_off, "amount_off": c.amount_off, "currency": c.currency} for c in page.data if c.valid]


class PlatformApi(Protocol):
    async def create_express_account(self, email: str, user_id: str, country: str) -> str:
        # Accounts v2: new Connect platforms can't create v1 `type=express` accounts.
        # Stripe won't grant transfers without card_payments, so request both.
        acct = await self.c.v2.core.accounts.create_async(
            {
                "contact_email": email,
                "identity": {"country": country.lower(), "entity_type": "individual"},
                "dashboard": "express",
                "defaults": {"responsibilities": {"fees_collector": "application", "losses_collector": "application"}},
                "configuration": {
                    "merchant": {"capabilities": {"card_payments": {"requested": True}}},
                    "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"requested": True}}}},
                },
                "metadata": {"kr_user": user_id},
            }
        )
        return acct.id

    async def onboarding_link(self, account_id: str, refresh_url: str, return_url: str) -> str: ...
    async def dashboard_link(self, account_id: str) -> str: ...
    async def payout_status(self, account_id: str) -> str: ...
    async def funding_checkout(self, payout_id: str, amount_cents: int, currency: str, description: str, success_url: str, cancel_url: str) -> tuple[str, str]: ...
    async def charge_for_session(self, session_id: str) -> str | None: ...
    async def transfer(self, amount_cents: int, currency: str, destination: str, source_charge: str | None, group: str, idempotency_key: str) -> str: ...


class PlatformStripe:
    def __init__(self, key: str | None = None):
        key = key or get_settings().platform_stripe_secret_key
        if not key:
            raise RuntimeError("PLATFORM_STRIPE_SECRET_KEY is not set; Stripe payouts are unavailable")
        self.c = _client(key)

    async def create_express_account(self, email: str, user_id: str, country: str) -> str:
        acct = await self.c.v1.accounts.create_async(
            {
                "type": "express",
                "country": country,
                "email": email,
                "capabilities": {"transfers": {"requested": True}},
                "business_type": "individual",
                "metadata": {"kr_user": user_id},
            }
        )
        return acct.id

    async def onboarding_link(self, account_id: str, refresh_url: str, return_url: str) -> str:
        link = await self.c.v1.account_links.create_async(
            {"account": account_id, "type": "account_onboarding", "refresh_url": refresh_url, "return_url": return_url}
        )
        return link.url

    async def dashboard_link(self, account_id: str) -> str:
        link = await self.c.v1.accounts.login_links.create_async(account_id)
        return link.url

    async def payout_status(self, account_id: str) -> str:
        """ready, verifying (Stripe is checking what was submitted), or needs_info."""
        acct = await self.c.v1.accounts.retrieve_async(account_id)
        if acct.payouts_enabled and (acct.capabilities or {}).get("transfers") == "active":
            return "ready"
        req = acct.requirements
        if req and not req.currently_due and not req.past_due and req.pending_verification:
            return "verifying"
        return "needs_info"

    async def funding_checkout(self, payout_id: str, amount_cents: int, currency: str, description: str, success_url: str, cancel_url: str) -> tuple[str, str]:
        s = await self.c.v1.checkout.sessions.create_async(
            {
                "mode": "payment",
                "line_items": [{"quantity": 1, "price_data": {"currency": currency, "unit_amount": amount_cents, "product_data": {"name": description}}}],
                "payment_intent_data": {"transfer_group": payout_id, "metadata": {"kr_payout": payout_id}},
                "metadata": {"kr_payout": payout_id},
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        return s.id, s.url or ""

    async def charge_for_session(self, session_id: str) -> str | None:
        s = await self.c.v1.checkout.sessions.retrieve_async(session_id, {"expand": ["payment_intent.latest_charge"]})
        pi = s.payment_intent
        if not pi or isinstance(pi, str):
            return None
        ch = pi.latest_charge
        return ch if isinstance(ch, str) or ch is None else ch.id

    async def transfer(self, amount_cents: int, currency: str, destination: str, source_charge: str | None, group: str, idempotency_key: str) -> str:
        params: dict = {"amount": amount_cents, "currency": currency, "destination": destination, "transfer_group": group}
        if source_charge:
            # Lets the transfer go out before the funding charge settles.
            params["source_transaction"] = source_charge
        t = await self.c.v1.transfers.create_async(params, {"idempotency_key": idempotency_key})  # type: ignore[arg-type]
        return t.id


class StripeOAuth:
    """Connect OAuth on Kickrail's account: a merchant clicks "Connect with Stripe",
    approves on stripe.com, and we keep only their account id. Stripe's OAuth calls
    are sync-only in stripe-python, so they run in a thread."""

    def __init__(self):
        s = get_settings()
        if not s.stripe_oauth:
            raise RuntimeError("Connect with Stripe isn't set up on this Kickrail instance")
        self.c = stripe.StripeClient(s.oauth_key, client_id=s.stripe_oauth_client_id)

    def authorize_url(self, state: str, redirect_uri: str, email: str | None = None) -> str:
        params: dict = {"response_type": "code", "scope": "read_write", "state": state, "redirect_uri": redirect_uri}
        if email:
            params["stripe_user"] = {"email": email}
        return self.c.oauth.authorize_url(params)  # type: ignore[arg-type]

    async def token(self, code: str) -> dict:
        import asyncio

        r = await asyncio.to_thread(self.c.oauth.token, {"grant_type": "authorization_code", "code": code})
        return {"account_id": r["stripe_user_id"], "livemode": bool(r.get("livemode"))}

    async def deauthorize(self, account_id: str) -> None:
        import asyncio

        await asyncio.to_thread(self.c.oauth.deauthorize, {"stripe_user_id": account_id})
