"""Custom rewards: for programs whose reward isn't cash (a discount, a free month, a
t-shirt). Kickrail decides when one is earned and keeps the record; the merchant hands
it out, from a reward.earned webhook or by hand, and marks it fulfilled.

A campaign with custom rewards carries:
  reward: {
    "type": "custom",
    "affiliate": {"description": "50% off forever", "on": "signup" | "first_payment" | "every_payment", "limit": "once" | "per_referral"},
    "customer": {"description": "25% off", "on": "signup" | "first_payment"} | None,
  }
Such a campaign earns no commissions, so nothing of it shows in payouts.

Each reward has a source_key that is unique per program, so a repeated Stripe event or
a race between two requests can't earn it twice. "once" rewards key on the affiliate,
which is what stops a second referral earning another one.
"""

from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from ..db import run_in_transaction
from ..domain.commission import is_custom
from ..ids import new_id
from ..serializers import reward_obj
from .outbox import emit


def _key(campaign: dict, recipient: str, referral: dict, payment_key: str | None) -> str:
    spec = campaign["reward"][recipient]
    if recipient == "affiliate" and spec["limit"] == "once":
        return f"rwd:{campaign['_id']}:{referral['affiliate_id']}"
    if spec["on"] == "every_payment":
        return f"rwd:{referral['_id']}:{recipient}:{payment_key}"
    return f"rwd:{referral['_id']}:{recipient}"


async def _earn(db: AsyncDatabase, merchant_id: str, campaign: dict, referral: dict, recipient: str, payment_key: str | None) -> dict | None:
    spec = campaign["reward"][recipient]
    doc = {
        "_id": new_id("rwd"),
        "merchant_id": merchant_id,
        "campaign_id": campaign["_id"],
        "affiliate_id": referral["affiliate_id"],
        "referral_id": referral["_id"],
        "recipient": recipient,
        "description": spec["description"],
        "trigger": spec["on"],
        "source_key": _key(campaign, recipient, referral, payment_key),
        "status": "earned",
        # Same rule as commissions: a possible self-referral waits for the merchant.
        "held": bool(referral.get("flags")) and not referral.get("flags_cleared"),
        "created_at": datetime.now(UTC),
    }
    if payment_key:
        doc["payment_key"] = payment_key

    async def create(tdb):
        await tdb.rewards.insert_one(doc)
        if not doc["held"]:
            await emit(tdb, merchant_id, "reward.earned", reward_obj(doc, referral))

    try:
        await run_in_transaction(db, create)
    except DuplicateKeyError:
        return None
    return doc


async def on_signup(db: AsyncDatabase, merchant: dict, referral: dict) -> list[dict]:
    campaign = await db.campaigns.find_one({"_id": referral["campaign_id"]})
    if not is_custom(campaign) or referral.get("test") or referral.get("rejected"):
        return []
    return await _for(db, merchant["_id"], campaign, referral, ("signup",), None)


async def on_payment(db: AsyncDatabase, merchant: dict, campaign: dict, referral: dict, payment_key: str, base_cents: int) -> str:
    if base_cents <= 0:
        return "no reward: nothing paid"
    # first_payment rewards key on the referral, so later payments find them already earned.
    earned = await _for(db, merchant["_id"], campaign, referral, ("first_payment", "every_payment"), payment_key)
    return f"rewards earned: {len(earned)}" if earned else "no reward"


async def _for(db, merchant_id: str, campaign: dict, referral: dict, triggers: tuple[str, ...], payment_key: str | None) -> list[dict]:
    out = []
    for recipient in ("affiliate", "customer"):
        spec = campaign["reward"].get(recipient)
        if spec and spec["on"] in triggers:
            if doc := await _earn(db, merchant_id, campaign, referral, recipient, payment_key):
                out.append(doc)
    return out


async def release(tdb, merchant_id: str, referral: dict) -> int:
    """The merchant cleared a flagged referral: its held rewards go out now."""
    n = 0
    async for r in tdb.rewards.find({"referral_id": referral["_id"], "held": True, "status": "earned"}):
        await tdb.rewards.update_one({"_id": r["_id"]}, {"$set": {"held": False}})
        await emit(tdb, merchant_id, "reward.earned", reward_obj({**r, "held": False}, referral))
        n += 1
    return n


async def void_unfulfilled(tdb, referral_id: str, reason: str) -> list[str]:
    """A rejected referral loses the rewards not handed out yet. The source_key is
    renamed so a later, legitimate referral can still earn a once-per-affiliate reward."""
    ids = []
    async for r in tdb.rewards.find({"referral_id": referral_id, "status": "earned"}, {"source_key": 1}):
        await tdb.rewards.update_one({"_id": r["_id"]}, {"$set": {"status": "void", "void_reason": reason, "source_key": f"{r['source_key']}:void:{r['_id']}"}})
        ids.append(r["_id"])
    return ids


class RewardError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


async def fulfill(db: AsyncDatabase, merchant_id: str, reward_id: str, note: str | None, by: str) -> dict:
    """Idempotent: fulfilling a fulfilled reward returns it unchanged, so a webhook
    handler that retries doesn't fail."""
    r = await db.rewards.find_one({"_id": reward_id, "merchant_id": merchant_id})
    if not r:
        raise RewardError(404, "reward not found")
    if r["status"] == "fulfilled":
        return r
    if r["status"] == "void":
        raise RewardError(409, "this reward was voided because its referral was rejected")
    if r.get("held"):
        raise RewardError(409, "this reward is held for review; approve the referral first")
    referral = await db.referrals.find_one({"_id": r["referral_id"]}) or {}
    done = {"status": "fulfilled", "fulfilled_at": datetime.now(UTC), "fulfilled_by": by, "note": (note or "").strip() or None}

    async def mark(tdb):
        res = await tdb.rewards.update_one({"_id": reward_id, "status": "earned"}, {"$set": done})
        if res.modified_count:
            await emit(tdb, merchant_id, "reward.fulfilled", reward_obj({**r, **done}, referral))

    await run_in_transaction(db, mark)
    return await db.rewards.find_one({"_id": reward_id})


async def unfulfill(db: AsyncDatabase, merchant_id: str, reward_id: str) -> dict:
    """Marked fulfilled by mistake: back to earned. No webhook, since nothing was handed out again."""
    res = await db.rewards.find_one_and_update(
        {"_id": reward_id, "merchant_id": merchant_id, "status": "fulfilled"},
        {"$set": {"status": "earned"}, "$unset": {"fulfilled_at": "", "fulfilled_by": "", "note": ""}},
        return_document=True,
    )
    if not res:
        raise RewardError(404, "no fulfilled reward with that id")
    return res
