import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import get_settings
from ..crypto import decrypt
from ..deps import merchant_api_factory, platform_api
from ..security import db_dep
from ..services import billing
from ..services.payouts import complete_funded_payout
from ..services.stripe_events import process_merchant_event

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_which(payload: bytes, signature: str, secrets: list[tuple[str, str]]) -> tuple[str, dict]:
    """The event and the name of the first secret that signed it."""
    text = payload.decode()
    for name, secret in secrets:
        if not secret:
            continue
        try:
            stripe.WebhookSignature.verify_header(text, signature, secret, tolerance=300)
            return name, json.loads(text)
        except stripe.SignatureVerificationError:
            continue
    raise HTTPException(400, "bad signature")


def _verify(payload: bytes, signature: str, secrets: list[str]) -> dict:
    return _verify_which(payload, signature, [("", s) for s in secrets])[1]


async def _once(db, endpoint: str, event: dict, merchant_id: str | None, handle: Callable[[], Awaitable[str]]) -> str:
    """Record the event and run `handle` unless an earlier delivery already finished it.
    Handlers stay idempotent on their own: this only saves repeat work and keeps a history."""
    now = datetime.now(UTC)
    prev = await db.stripe_events.find_one_and_update(
        {"_id": event["id"]},
        {
            "$setOnInsert": {"endpoint": endpoint, "type": event.get("type"), "account": event.get("account"), "livemode": event.get("livemode"), "created": event.get("created"), "received_at": now},
            "$set": {"last_received_at": now},
            "$inc": {"deliveries": 1},
        },
        upsert=True,
    )
    if prev and prev.get("status") == "done":
        return "duplicate"
    try:
        outcome = await handle()
    except Exception as e:
        await db.stripe_events.update_one({"_id": event["id"]}, {"$set": {"status": "failed", "error": f"{type(e).__name__}: {e}"[:500], "merchant_id": merchant_id}})
        raise
    await db.stripe_events.update_one({"_id": event["id"]}, {"$set": {"status": "done", "outcome": outcome, "merchant_id": merchant_id, "done_at": datetime.now(UTC)}, "$unset": {"error": ""}})
    return outcome


@router.post("/stripe/{merchant_id}")
async def merchant_webhook(merchant_id: str, request: Request, db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    m = await db.merchants.find_one({"_id": merchant_id})
    if not m or not m.get("stripe", {}).get("webhook_secret_enc"):
        raise HTTPException(404, "unknown merchant")
    event = _verify(await request.body(), request.headers.get("stripe-signature", ""), [decrypt(m["stripe"]["webhook_secret_enc"])])
    # Errors propagate as 500 so Stripe retries; processing is idempotent.
    outcome = await _once(db, "merchant", event, merchant_id, lambda: process_merchant_event(db, m, event, factory(m)))
    log.info("merchant %s %s %s -> %s", merchant_id, event["type"], event["id"], outcome)
    return {"outcome": outcome}


async def _billing_event(db, endpoint: str, event: dict) -> dict:
    """An event from the billing account. That account may be shared with other products, so
    anything not for a Kickrail program gets a 200 and nothing else: not even a record."""
    mid = await billing.owner_of(db, event)
    if not mid:
        log.info("%s %s %s -> not Kickrail's, ignored", endpoint, event.get("type"), event.get("id"))
        return {"outcome": "ignored"}

    async def handle() -> str:
        return await billing.handle_event(db, event) or "ignored"

    outcome = await _once(db, endpoint, event, mid, handle)
    log.info("%s %s %s -> %s", endpoint, event["type"], event["id"], outcome)
    return {"outcome": outcome}


@router.post("/billing")
async def billing_webhook(request: Request, db=Depends(db_dep)):
    """Kickrail's plan billing (KR_BILLING_STRIPE_WEBHOOK_SECRET). Only billing logic runs here."""
    _, event = _verify_which(await request.body(), request.headers.get("stripe-signature", ""), [("billing", get_settings().billing_stripe_webhook_secret)])
    return await _billing_event(db, "billing", event)


@router.post("/platform")
async def platform_webhook(request: Request, db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    s = get_settings()
    signed_by, event = _verify_which(
        await request.body(), request.headers.get("stripe-signature", ""),
        [("platform", s.platform_stripe_webhook_secret), ("connect", s.platform_stripe_connect_webhook_secret), ("billing", s.billing_stripe_webhook_secret)],
    )
    if signed_by == "billing":
        # A billing endpoint still pointed here. Its account may not be the platform one, so
        # its events only ever reach billing, never Connect or payout handling.
        return await _billing_event(db, "billing", event)
    obj = event["data"]["object"]
    # Merchants who connected with one click send their events through Kickrail's Connect endpoint.
    m = await db.merchants.find_one({"stripe.account_id": event["account"], "stripe.oauth": True}) if event.get("account") else None

    async def handle() -> str:
        if m and event["type"] == "account.application.deauthorized":
            await db.merchants.update_one({"_id": m["_id"], "stripe.account_id": event["account"]}, {"$unset": {"stripe": ""}})
            return "merchant disconnected"
        elif m:
            return await process_merchant_event(db, m, event, factory(m))
        elif event["type"] == "checkout.session.completed" and (obj.get("metadata") or {}).get("kr_payout"):
            return await complete_funded_payout(db, obj["metadata"]["kr_payout"], obj["id"], platform_api())
        elif not event.get("account") and (handled := await billing.handle_event(db, event)) is not None:
            # Plans billed on the platform account itself (before billing had its own account).
            return handled
        elif event["type"] == "account.updated":
            enabled = bool(obj.get("payouts_enabled")) and (obj.get("capabilities") or {}).get("transfers") == "active"
            res = await db.partners.update_one({"connect_account_id": obj["id"]}, {"$set": {"payouts_enabled": enabled}})
            return f"payouts_enabled={enabled}" if res.matched_count else "unknown account"
        else:
            return "ignored"

    outcome = await _once(db, "platform", event, m["_id"] if m else None, handle)
    log.info("platform %s %s -> %s", event["type"], event["id"], outcome)
    return {"outcome": outcome}
