"""Write who referred a customer onto their Stripe customer, so the merchant sees it in
their Stripe dashboard and their own code can read it from customer.metadata.

A referral that gains a Stripe customer, or moves to another affiliate, is marked
`stripe_sync_due`; the dispatcher writes it in the background and retries on errors.
The keys are kickrail_* so they never look like the kr_ref / kr_via / kr_code we read.
"""

import logging
from datetime import UTC, datetime, timedelta

import stripe
from pymongo.asynchronous.database import AsyncDatabase

from .outbox import wake

log = logging.getLogger(__name__)

# Minutes to wait after the Nth failure; then it's given up.
RETRY_MINUTES = [1, 10, 60, 360]
BATCH = 50


def customer_metadata(referral: dict, affiliate: dict | None) -> dict:
    return {
        "kickrail_referral": referral["_id"],
        "kickrail_affiliate": referral["affiliate_id"],
        "kickrail_affiliate_token": (affiliate or {}).get("token") or "",
        "kickrail_campaign": referral.get("campaign_id") or "",
    }


async def mark_merchant(db: AsyncDatabase, merchant_id: str) -> None:
    """Queue every referral with a Stripe customer, e.g. after (re)connecting Stripe."""
    await db.referrals.update_many({"merchant_id": merchant_id, "stripe_customer_id": {"$type": "string"}}, {"$set": {"stripe_sync_due": True}, "$unset": {"stripe_sync_error": ""}})
    wake()


async def sync_customers(db: AsyncDatabase, factory, now: datetime | None = None) -> int:
    """One pass: write up to BATCH due referrals. Returns how many were written."""
    now = now or datetime.now(UTC)
    due = {"stripe_sync_due": True, "$or": [{"stripe_sync_retry_at": {"$exists": False}}, {"stripe_sync_retry_at": {"$lte": now}}]}
    merchants: dict[str, dict | None] = {}
    written = 0
    async for r in db.referrals.find(due).limit(BATCH):
        mid = r["merchant_id"]
        if mid not in merchants:
            merchants[mid] = await db.merchants.find_one({"_id": mid})
        m = merchants[mid]
        # Only clear the mark if nothing changed while we were talking to Stripe.
        same = {"_id": r["_id"], "affiliate_id": r["affiliate_id"], "stripe_customer_id": r.get("stripe_customer_id")}
        done = {"$unset": {"stripe_sync_due": "", "stripe_sync_retry_at": "", "stripe_sync_attempts": ""}}
        if not r.get("stripe_customer_id") or not m or not m.get("stripe"):
            await db.referrals.update_one(same, done)
            continue
        try:
            aff = await db.affiliates.find_one({"_id": r["affiliate_id"]}, {"token": 1})
            await factory(m).update_customer_metadata(r["stripe_customer_id"], customer_metadata(r, aff))
        except (stripe.PermissionError, stripe.AuthenticationError, stripe.InvalidRequestError) as e:
            # The key can't write customers, or the customer is gone: retrying won't help.
            await db.referrals.update_one(same, done | {"$set": {"stripe_sync_error": (e.user_message or str(e))[:300]}})
            continue
        except Exception as e:
            attempts = r.get("stripe_sync_attempts", 0)
            log.warning("stripe customer sync failed for %s", r["_id"], exc_info=True)
            if attempts >= len(RETRY_MINUTES):
                await db.referrals.update_one(same, done | {"$set": {"stripe_sync_error": f"{type(e).__name__}: {e}"[:300]}})
            else:
                await db.referrals.update_one(same, {"$set": {"stripe_sync_retry_at": now + timedelta(minutes=RETRY_MINUTES[attempts]), "stripe_sync_attempts": attempts + 1}})
            continue
        await db.referrals.update_one(same, {"$set": {"stripe_synced_at": now}, "$unset": done["$unset"] | {"stripe_sync_error": ""}})
        written += 1
    return written
