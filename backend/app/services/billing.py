"""Kickrail charging programs for their plan, on Kickrail's own (platform) Stripe account.

Prices are found by lookup key (kickrail_<plan>_<month|year>) and created the first
time they're needed, so a fresh Stripe account needs no setup. A program's plan is
whatever its subscription says (synced from webhooks); without one it's on the free
plan, or on the no-card Growth trial while that lasts.

The revenue meter adds up referred revenue per calendar month, in USD at rough fixed
rates. Going over the plan's cap never stops tracking: after two full months over,
the dashboard shows a notice and the owner gets one email a month.
"""

import logging
from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from .. import plans
from ..config import get_settings

log = logging.getLogger(__name__)

# USD per unit of each currency. Close enough for a soft limit.
USD_RATE = {
    "usd": 1.0, "cad": 0.72, "eur": 1.08, "gbp": 1.27, "aud": 0.65, "nzd": 0.6, "chf": 1.12, "sek": 0.095, "nok": 0.093, "dkk": 0.145,
    "inr": 0.012, "brl": 0.18, "mxn": 0.055, "sgd": 0.74, "hkd": 0.128, "jpy": 0.0067, "krw": 0.00073, "pln": 0.25, "zar": 0.055, "aed": 0.27,
}
ZERO_DECIMAL = {"jpy", "krw", "vnd", "clp", "pyg", "ugx", "xaf", "xof", "bif", "djf", "gnf", "kmf", "mga", "rwf", "vuv", "xpf"}


def to_usd_cents(amount: int, currency: str) -> int:
    c = currency.lower()
    units = amount if c in ZERO_DECIMAL else amount / 100
    return round(units * USD_RATE.get(c, 1.0) * 100)


def month_key(d: datetime) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_back(now: datetime, n: int) -> datetime:
    y, mo = now.year, now.month - n
    while mo < 1:
        y, mo = y - 1, mo + 12
    return datetime(y, mo, 1, tzinfo=UTC)


async def monthly_revenue(db: AsyncDatabase, merchant_id: str, now: datetime | None = None, months: int = 3) -> dict[str, int]:
    """Referred revenue in USD cents by month ("2026-10"), this month and the `months - 1` before it."""
    now = now or datetime.now(UTC)
    start = months_back(now, months - 1)
    out = {month_key(months_back(now, i)): 0 for i in range(months)}
    pipeline = [
        {"$match": {"merchant_id": merchant_id, "status": {"$ne": "void"}, "base_cents": {"$gt": 0}, "created_at": {"$gte": start}}},
        {"$group": {"_id": {"m": {"$dateToString": {"format": "%Y-%m", "date": "$created_at"}}, "c": "$currency"}, "t": {"$sum": "$base_cents"}}},
    ]
    async for row in await db.commissions.aggregate(pipeline):
        if row["_id"]["m"] in out:
            out[row["_id"]["m"]] += to_usd_cents(row["t"], row["_id"]["c"])
    return out


async def usage(db: AsyncDatabase, m: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    plan = plans.current(m, now)
    by_month = await monthly_revenue(db, m["_id"], now)
    cap = plan["revenue_cap"]
    full = [month_key(months_back(now, 1)), month_key(months_back(now, 2))]
    over = cap is not None and all(by_month[k] > cap * 100 for k in full)
    return {
        "this_month_cents": by_month[month_key(now)],
        "months": [{"month": k, "revenue_cents": v} for k, v in by_month.items()],
        "cap_cents": cap * 100 if cap is not None else None,
        "over_limit": over,
        "suggested_plan": _fits(max(by_month[k] for k in full)) if over else None,
    }


def _fits(revenue_cents: int) -> str:
    for pid in plans.ORDER:
        if plans.PLANS[pid]["revenue_cap"] * 100 >= revenue_cents:
            return pid
    return "scale"


async def check_limits(db: AsyncDatabase, now: datetime | None = None) -> int:
    """Once a month per program: work out whether the last two full months were over the
    cap, store it for the dashboard banner, and email the owner when they were."""
    now = now or datetime.now(UTC)
    key = month_key(now)
    sent = 0
    async for m in db.merchants.find({"usage.checked_month": {"$ne": key}}).limit(200):
        u = await usage(db, m, now)
        await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"usage": {"checked_month": key, "over_limit": u["over_limit"], "suggested_plan": u["suggested_plan"]}}})
        if u["over_limit"]:
            await _over_limit_email(db, m, u)
            sent += 1
    return sent


async def _over_limit_email(db: AsyncDatabase, m: dict, u: dict) -> None:
    from .notify import account_email

    owner = await db.users.find_one({"_id": m.get("owner_id")}, {"email": 1})
    if not owner:
        return
    plan = plans.current(m)
    cap = u["cap_cents"] // 100
    nxt = plans.PLANS[u["suggested_plan"]]
    await account_email(
        db, owner["email"], "plan_over_limit", f"{m['name']} has outgrown the {plan['name']} plan", f"{m['name']} is growing",
        [
            f"Affiliates brought {m['name']} more than ${cap:,} a month for the last two months, which is past what the {plan['name']} plan covers.",
            f"Tracking and commissions keep running as normal. The {nxt['name']} plan (${nxt['month']}/month) covers up to ${nxt['revenue_cap']:,} a month.",
        ],
        ("See plans", f"{get_settings().public_url}/dashboard/billing"),
    )


# ---------- Stripe ----------


class Billing:
    """Kickrail's own Stripe account, for charging programs."""

    _prices: dict[str, str] = {}

    def __init__(self, key: str | None = None):
        import stripe

        key = key or get_settings().billing_key
        if not key:
            raise RuntimeError("billing isn't set up on this Kickrail instance")
        self.c = stripe.StripeClient(key, http_client=stripe.HTTPXClient(allow_sync_methods=False))

    async def price_id(self, plan: str, interval: str) -> str:
        import stripe

        lookup = f"kickrail_{plan}_{interval}"
        if lookup in self._prices:
            return self._prices[lookup]
        found = await self.c.v1.prices.list_async({"lookup_keys": [lookup], "active": True, "limit": 1})
        if found.data:
            price = found.data[0].id
        else:
            info = plans.PLANS[plan]
            try:
                product = (await self.c.v1.products.retrieve_async(f"kickrail_{plan}")).id
            except stripe.InvalidRequestError:
                product = (await self.c.v1.products.create_async({"id": f"kickrail_{plan}", "name": f"Kickrail {info['name']}", "metadata": {"kr_plan": plan}})).id
            price = (
                await self.c.v1.prices.create_async(
                    {
                        "product": product, "currency": "usd", "unit_amount": info[interval] * 100, "recurring": {"interval": interval},
                        "lookup_key": lookup, "metadata": {"kr_plan": plan}, "nickname": f"{info['name']} {interval}ly",
                    }
                )
            ).id
        self._prices[lookup] = price
        return price

    async def checkout(self, *, merchant_id: str, customer: str | None, email: str, price: str, trial_end: int | None, success_url: str, cancel_url: str) -> str:
        sub: dict = {"metadata": {"kr_merchant": merchant_id}}
        if trial_end:
            sub["trial_end"] = trial_end
        params: dict = {
            "mode": "subscription",
            "line_items": [{"price": price, "quantity": 1}],
            "subscription_data": sub,
            "metadata": {"kr_merchant": merchant_id},
            "client_reference_id": merchant_id,
            "allow_promotion_codes": True,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        params |= {"customer": customer} if customer else {"customer_email": email}
        s = await self.c.v1.checkout.sessions.create_async(params)  # type: ignore[arg-type]
        return s.url or ""

    async def change_price(self, subscription_id: str, price: str) -> dict:
        sub = await self.c.v1.subscriptions.retrieve_async(subscription_id)
        item = sub["items"]["data"][0]["id"]
        new = await self.c.v1.subscriptions.update_async(
            subscription_id, {"items": [{"id": item, "price": price}], "proration_behavior": "create_prorations", "cancel_at_period_end": False}
        )
        return new.to_dict()

    async def portal(self, customer: str, return_url: str) -> str:
        configs = await self.c.v1.billing_portal.configurations.list_async({"active": True, "limit": 10})
        config = next((c.id for c in configs.data if (c.metadata or {}).get("kr") == "billing"), None)
        if not config:
            config = (
                await self.c.v1.billing_portal.configurations.create_async(
                    {
                        "business_profile": {"headline": "Kickrail billing"},
                        "features": {
                            "invoice_history": {"enabled": True},
                            "payment_method_update": {"enabled": True},
                            "customer_update": {"enabled": True, "allowed_updates": ["email", "address", "tax_id", "name"]},
                            "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                        },
                        "metadata": {"kr": "billing"},
                    }
                )
            ).id
        s = await self.c.v1.billing_portal.sessions.create_async({"customer": customer, "return_url": return_url, "configuration": config})
        return s.url


def _ts(v) -> datetime | None:
    return datetime.fromtimestamp(v, UTC) if v else None


def _plan_of(sub: dict) -> tuple[str | None, str | None]:
    item = ((sub.get("items") or {}).get("data") or [{}])[0]
    price = item.get("price") or {}
    pid = (price.get("metadata") or {}).get("kr_plan")
    if not pid and (price.get("lookup_key") or "").startswith("kickrail_"):
        pid = price["lookup_key"].split("_")[1]
    return (pid if pid in plans.PLANS else None), (price.get("recurring") or {}).get("interval")


async def apply_subscription(db: AsyncDatabase, sub: dict, *, deleted: bool = False, at: int | None = None) -> str:
    """Copy a Kickrail subscription onto the program it's for."""
    mid = (sub.get("metadata") or {}).get("kr_merchant")
    m = await db.merchants.find_one({"_id": mid} if mid else {"plan.stripe_subscription": sub["id"]})
    if not m:
        return "unknown program"
    cur = m.get("plan") or {}
    if cur.get("stripe_subscription") and cur["stripe_subscription"] != sub["id"] and cur.get("status") not in ("canceled", "incomplete_expired"):
        return "older subscription, ignored"
    if at and cur.get("stripe_subscription") == sub["id"] and cur.get("synced_at", 0) > at:
        return "stale event"
    pid, interval = _plan_of(sub)
    if not pid:
        return "not a Kickrail plan"
    item = ((sub.get("items") or {}).get("data") or [{}])[0]
    status = "canceled" if deleted else sub["status"]
    plan = {
        "id": pid,
        "interval": interval,
        "status": status,
        "stripe_customer": sub["customer"] if isinstance(sub["customer"], str) else sub["customer"]["id"],
        "stripe_subscription": sub["id"],
        "current_period_end": _ts(item.get("current_period_end") or sub.get("current_period_end")),
        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")) or bool(sub.get("cancel_at")),
        "trial_ends_at": _ts(sub.get("trial_end")) if status == "trialing" else None,
        "synced_at": at or int(datetime.now(UTC).timestamp()),
    }
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"plan": plan}, "$unset": {"usage.checked_month": ""}})
    return f"{pid} {status}"


async def handle_event(db: AsyncDatabase, event: dict) -> str | None:
    """Platform webhook events about Kickrail's own billing; None if it isn't one."""
    obj, kind = event["data"]["object"], event["type"]
    if kind == "checkout.session.completed" and (obj.get("metadata") or {}).get("kr_merchant") and obj.get("mode") == "subscription":
        # The plan itself comes with customer.subscription.created.
        await db.merchants.update_one({"_id": obj["metadata"]["kr_merchant"]}, {"$set": {"plan.stripe_customer": obj.get("customer")}})
        return "checkout recorded"
    if kind in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        return await apply_subscription(db, obj, deleted=kind.endswith("deleted"), at=event.get("created"))
    return None

