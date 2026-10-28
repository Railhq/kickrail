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


def _verify(payload: bytes, signature: str, secrets: list[str]) -> dict:
    text = payload.decode()
    for secret in secrets:
        if not secret:
            continue
        try:
            stripe.WebhookSignature.verify_header(text, signature, secret, tolerance=300)
            return json.loads(text)
        except stripe.SignatureVerificationError:
            continue
    raise HTTPException(400, "bad signature")


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


@router.post("/platform")
async def platform_webhook(request: Request, db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    s = get_settings()
    event = _verify(await request.body(), request.headers.get("stripe-signature", ""), [s.platform_stripe_webhook_secret, s.platform_stripe_connect_webhook_secret, s.billing_stripe_webhook_secret])
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
        elif (handled := await billing.handle_event(db, event)) is not None:
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
