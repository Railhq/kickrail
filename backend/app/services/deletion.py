"""Merchant-initiated deletes of referrals and commissions.

Nothing paid can be deleted: a paid commission, or one sitting in a payout, is part of
that payout's record, so the payout has to be undone first. Each delete keeps a full
copy of the row in deleted_records and writes an audit entry, in the same transaction.
A deleted commission's source_key stays in deleted_records, so a payment Stripe sends
again doesn't bring it back.
"""

from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from ..db import run_in_transaction
from ..ids import new_id
from . import audit, notify


class NotFound(Exception):
    pass


class Blocked(Exception):
    pass


def _locked(c: dict) -> bool:
    return c["status"] == "paid" or bool(c.get("payout_id"))


def _tombstone(merchant_id: str, kind: str, doc: dict, now: datetime, reason: str | None) -> dict:
    t = {"_id": new_id("del"), "merchant_id": merchant_id, "kind": kind, "record_id": doc["_id"], "doc": doc, "reason": reason, "actor": audit.actor.get() or {"kind": "system"}, "deleted_at": now}
    if kind == "commission":
        t["source_key"] = doc["source_key"]
    return t


async def delete_commission(db: AsyncDatabase, merchant_id: str, commission_id: str, reason: str | None = None) -> dict:
    async def run(tdb) -> dict:
        c = await tdb.commissions.find_one({"_id": commission_id, "merchant_id": merchant_id})
        if not c:
            raise NotFound
        if _locked(c):
            raise Blocked("This commission is paid or in a payout. Undo or cancel the payout first.")
        if await tdb.commissions.find_one({"clawback_of": c["_id"]}, {"_id": 1}):
            raise Blocked("This commission has a refund clawback against it. Delete the clawback first.")
        now = datetime.now(UTC)
        await tdb.deleted_records.insert_one(_tombstone(merchant_id, "commission", c, now, reason))
        await tdb.commissions.delete_one({"_id": c["_id"]})
        await audit.record(
            tdb, merchant_id, "commission.deleted", c["_id"], affiliate_id=c["affiliate_id"], referral_id=c.get("referral_id"),
            amount_cents=c["amount_cents"], currency=c["currency"], status=c["status"], source=c["source_key"], reason=reason,
        )
        await notify.commission_deleted(tdb, merchant_id, c)
        return c

    return await run_in_transaction(db, run)


async def delete_referral(db: AsyncDatabase, merchant_id: str, referral_id: str, reason: str | None = None) -> tuple[dict, list[dict]]:
    """Deletes the referral and its unpaid commissions. Returns both."""

    async def run(tdb) -> tuple[dict, list[dict]]:
        r = await tdb.referrals.find_one({"_id": referral_id, "merchant_id": merchant_id})
        if not r:
            raise NotFound
        commissions = await tdb.commissions.find({"referral_id": referral_id}).to_list(None)
        if any(_locked(c) for c in commissions):
            raise Blocked("This referral has paid commissions, or commissions in a payout. Undo or cancel those payouts first, or reject the referral instead.")
        now = datetime.now(UTC)
        await tdb.deleted_records.insert_many([_tombstone(merchant_id, "commission", c, now, reason) for c in commissions] + [_tombstone(merchant_id, "referral", r, now, reason)])
        await tdb.commissions.delete_many({"_id": {"$in": [c["_id"] for c in commissions]}})
        await tdb.referrals.delete_one({"_id": r["_id"]})
        await audit.record(
            tdb, merchant_id, "referral.deleted", r["_id"], affiliate_id=r["affiliate_id"], email=r.get("email"), stripe_customer_id=r.get("stripe_customer_id"),
            commissions_deleted=[c["_id"] for c in commissions], amount_cents=sum(c["amount_cents"] for c in commissions), reason=reason,
        )
        for c in commissions:
            await notify.commission_deleted(tdb, merchant_id, c)
        await notify.referral_deleted(tdb, merchant_id, r)
        return r, commissions

    return await run_in_transaction(db, run)
