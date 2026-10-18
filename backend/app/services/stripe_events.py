"""Turn a merchant's Stripe events into referrals and commissions.

Everything is idempotent: Stripe retries, and the same payment can arrive as both
checkout.session.completed and invoice.paid. Commissions are keyed by sourceKey
("inv:<id>" / "cs:<id>"), so a replay never pays twice.
"""

import logging
from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from ..domain.commission import Line, decide_commission, decide_refund
from ..ids import new_id
from . import notify
from .referrals import AttachInput, attach_referral
from .stripe_api import MerchantApi

log = logging.getLogger(__name__)


def _ts(seconds: int | None) -> datetime:
    return datetime.fromtimestamp(seconds, UTC) if seconds else datetime.now(UTC)


def _id(v) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else v.get("id")


def invoice_lines(inv: dict) -> list[Line]:
    """Handles both line shapes: line.price (older API versions) and
    line.pricing.price_details (2025-03 onwards)."""
    out = []
    for l in (inv.get("lines") or {}).get("data") or []:
        price = l.get("price")
        details = (l.get("pricing") or {}).get("price_details") or {}
        price_id = _id(price) or details.get("price")
        product_id = (price.get("product") if isinstance(price, dict) else None) or details.get("product")
        out.append(Line(l.get("amount") or 0, _id(product_id), price_id))
    return out


def _promotion_code(discounts) -> str | None:
    for d in discounts or []:
        if isinstance(d, dict) and d.get("promotion_code"):
            return _id(d["promotion_code"])
    return None


async def process_merchant_event(db: AsyncDatabase, merchant: dict, event: dict, api: MerchantApi) -> str:
    """Returns a short outcome string, stored with the event for debugging."""
    key = f"{merchant['_id']}:{event['id']}"
    if await db.stripe_events.find_one({"_id": key}):
        return "duplicate"
    obj = event["data"]["object"]
    handler = HANDLERS.get(event["type"])
    outcome = await handler(db, merchant, obj, api) if handler else "ignored"
    try:
        await db.stripe_events.insert_one({"_id": key, "type": event["type"], "outcome": outcome, "received_at": datetime.now(UTC)})
    except DuplicateKeyError:
        pass
    return outcome


async def _checkout_completed(db, merchant, s: dict, api: MerchantApi) -> str:
    meta = s.get("metadata") or {}
    ref = s.get("client_reference_id") or ""
    hit = await attach_referral(
        db,
        merchant,
        AttachInput(
            click_id=ref if ref.startswith("kr_") else meta.get("kr_ref"),
            token=meta.get("kr_via"),
            promotion_code_id=_promotion_code(s.get("discounts")),
            email=(s.get("customer_details") or {}).get("email") or s.get("customer_email"),
            stripe_customer_id=_id(s.get("customer")),
        ),
        getattr(api, "customer_created", None),
    )
    if not hit:
        return "no referral"
    referral, _ = hit
    # Subscriptions earn on invoice.paid; only one-off payments earn here.
    if s.get("mode") != "payment" or s.get("payment_status") != "paid":
        return "referral linked"
    tax = (s.get("total_details") or {}).get("amount_tax") or 0
    lines = None
    if hasattr(api, "checkout_lines"):
        try:
            lines = await api.checkout_lines(s["id"])
        except Exception:  # product rules then fall back to the campaign rule
            log.warning("line item lookup failed for %s", s["id"], exc_info=True)
    return await earn(db, merchant, referral, f"cs:{s['id']}", (s.get("amount_total") or 0) - tax, s["currency"], _ts(s.get("created")), _id(s.get("payment_intent")), lines)


async def _customer(db, merchant, c: dict, api: MerchantApi) -> str:
    meta = c.get("metadata") or {}
    if not (meta.get("kr_ref") or meta.get("kr_via") or meta.get("kr_code")):
        return "no referral metadata"
    hit = await attach_referral(
        db, merchant, AttachInput(click_id=meta.get("kr_ref"), token=meta.get("kr_via"), code=meta.get("kr_code"), email=c.get("email"), stripe_customer_id=c["id"])
    )
    return "referral linked" if hit else "no referral"


async def _invoice_paid(db, merchant, inv: dict, api: MerchantApi) -> str:
    customer = _id(inv.get("customer"))
    hit = await attach_referral(
        db, merchant, AttachInput(email=inv.get("customer_email"), stripe_customer_id=customer, promotion_code_id=_promotion_code(inv.get("discounts"))),
        getattr(api, "customer_created", None),
    )
    if not hit:
        return "no referral"
    referral, _ = hit
    taxes = sum(t.get("amount", 0) for t in inv.get("total_taxes") or [])
    base = (inv.get("amount_paid") or 0) - taxes
    paid_at = _ts((inv.get("status_transitions") or {}).get("paid_at") or inv.get("created"))
    try:
        pi = await api.payment_intent_for_invoice(inv["id"])
    except Exception:  # missing permission or network: refunds fall back to an invoice lookup
        log.warning("payment intent lookup failed for %s", inv["id"], exc_info=True)
        pi = None
    return await earn(db, merchant, referral, f"inv:{inv['id']}", base, inv["currency"], paid_at, pi, invoice_lines(inv))


async def earn(
    db: AsyncDatabase, merchant: dict, referral: dict, source_key: str, base_cents: int, currency: str, paid_at: datetime,
    payment_intent_id: str | None, lines: list[Line] | None = None,
) -> str:
    if await db.commissions.find_one({"merchant_id": merchant["_id"], "source_key": source_key}):
        return "already earned"
    campaign = await db.campaigns.find_one({"_id": referral["campaign_id"]})
    if not campaign:
        return "campaign missing"
    affiliate = await db.affiliates.find_one({"_id": referral["affiliate_id"]})

    first_paid_at = referral.get("first_paid_at") or paid_at
    if base_cents > 0 and not referral.get("first_paid_at"):
        await db.referrals.update_one({"_id": referral["_id"]}, {"$set": {"first_paid_at": paid_at, "status": "customer"}})
        await notify.referral_converted(db, merchant["_id"], {**referral, "first_paid_at": paid_at, "status": "customer"})

    # Lead bounties are paid for the signup, so they don't use up a one-time sale commission.
    prior = await db.commissions.count_documents({"referral_id": referral["_id"], "status": {"$ne": "void"}, "amount_cents": {"$gt": 0}, "kind": {"$ne": "lead"}})
    d = decide_commission(campaign, base_cents, currency, paid_at, first_paid_at, prior, affiliate, lines)
    if not d.ok:
        return f"no commission: {d.reason}"

    doc = {
        "_id": new_id("com"),
        "merchant_id": merchant["_id"],
        "affiliate_id": referral["affiliate_id"],
        "referral_id": referral["_id"],
        "campaign_id": campaign["_id"],
        "source_key": source_key,
        "base_cents": base_cents,
        "original_amount_cents": d.amount_cents,
        "amount_cents": d.amount_cents,
        "refunded_cents": 0,
        "currency": d.currency,
        "status": "pending",
        # Flagged referrals (possible self-referral) wait for the merchant to clear them.
        "held": bool(referral.get("flags")) and not referral.get("flags_cleared"),
        "due_at": d.due_at,
        "created_at": datetime.now(UTC),
    }
    if payment_intent_id:
        doc["payment_intent_id"] = payment_intent_id
    try:
        await db.commissions.insert_one(doc)
    except DuplicateKeyError:
        return "already earned"
    await notify.commission_created(db, merchant, doc)
    return f"commission {d.amount_cents} {d.currency}"


async def _find_commission_for_payment(db, merchant, payment_intent_id: str | None, api: MerchantApi) -> dict | None:
    if not payment_intent_id:
        return None
    c = await db.commissions.find_one({"merchant_id": merchant["_id"], "payment_intent_id": payment_intent_id, "amount_cents": {"$gt": 0}})
    if c:
        return c
    try:
        invoice_id = await api.invoice_for_payment_intent(payment_intent_id)
    except Exception:
        log.warning("invoice lookup failed for %s", payment_intent_id, exc_info=True)
        invoice_id = None
    if invoice_id:
        return await db.commissions.find_one({"merchant_id": merchant["_id"], "source_key": f"inv:{invoice_id}"})
    return None


async def apply_reversal(db: AsyncDatabase, commission: dict, newly_reversed_cents: int, charge_cents: int, key: str) -> str:
    action = decide_refund(commission["status"], commission["original_amount_cents"], commission["amount_cents"], newly_reversed_cents, charge_cents)
    inc = {"refunded_cents": newly_reversed_cents}
    if action.kind == "none":
        return "nothing to reverse"
    if action.kind == "reduce":
        await db.commissions.update_one({"_id": commission["_id"]}, {"$set": {"amount_cents": action.amount_cents}, "$inc": inc})
        await notify.commission_updated(db, commission["merchant_id"], commission["_id"])
        return f"reduced to {action.amount_cents}"
    if action.kind == "void":
        await db.commissions.update_one({"_id": commission["_id"]}, {"$set": {"status": "void", "amount_cents": 0, "void_reason": "refunded"}, "$inc": inc})
        await notify.commission_updated(db, commission["merchant_id"], commission["_id"])
        return "voided"
    clawback_id = new_id("com")
    try:
        await db.commissions.insert_one(
            {
                "_id": clawback_id,
                "merchant_id": commission["merchant_id"],
                "affiliate_id": commission["affiliate_id"],
                "referral_id": commission["referral_id"],
                "campaign_id": commission["campaign_id"],
                "source_key": f"clawback:{key}",
                "clawback_of": commission["_id"],
                "base_cents": 0,
                "original_amount_cents": action.amount_cents,
                "amount_cents": action.amount_cents,
                "refunded_cents": 0,
                "currency": commission["currency"],
                "status": "pending",
                "held": False,
                "due_at": datetime.now(UTC),
                "created_at": datetime.now(UTC),
            }
        )
    except DuplicateKeyError:
        return "already clawed back"
    await db.commissions.update_one({"_id": commission["_id"]}, {"$inc": inc})
    await notify.commission_updated(db, commission["merchant_id"], clawback_id, "commission.created")
    return f"clawback {action.amount_cents}"


async def _charge_refunded(db, merchant, ch: dict, api: MerchantApi) -> str:
    commission = await _find_commission_for_payment(db, merchant, _id(ch.get("payment_intent")), api)
    if not commission:
        return "no commission for charge"
    # amount_refunded is cumulative; refunded_cents tracks what we already applied.
    newly = (ch.get("amount_refunded") or 0) - commission.get("refunded_cents", 0)
    return await apply_reversal(db, commission, newly, ch.get("amount") or 0, f"{ch['id']}:{ch.get('amount_refunded')}")


async def _dispute_created(db, merchant, dispute: dict, api: MerchantApi) -> str:
    commission = await _find_commission_for_payment(db, merchant, _id(dispute.get("payment_intent")), api)
    if not commission:
        return "no commission for dispute"
    charge_cents = commission["base_cents"] or dispute.get("amount") or 0
    return await apply_reversal(db, commission, dispute.get("amount") or 0, max(charge_cents, dispute.get("amount") or 0), dispute["id"])


HANDLERS = {
    "checkout.session.completed": _checkout_completed,
    "customer.created": _customer,
    "customer.updated": _customer,
    "invoice.paid": _invoice_paid,
    "charge.refunded": _charge_refunded,
    "charge.dispute.created": _dispute_created,
}

