"""Who did what to money: affiliate approvals, rate changes, cleared flags, rejected
signups and the commissions they voided, payouts, and the accounts money comes from
or goes out through. Kept for good; the program's team can read it."""

from contextvars import ContextVar
from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from ..ids import new_id

# Set by the auth dependencies (and the MCP endpoint), so records name who acted
# without every caller passing it along.
actor: ContextVar[dict | None] = ContextVar("kr_actor", default=None)


def as_user(user: dict) -> None:
    actor.set({"kind": "user", "id": user["_id"], "email": user.get("email", "")})


async def record(db: AsyncDatabase, merchant_id: str, action: str, target: str, **detail) -> None:
    await db.audit_log.insert_one(
        {"_id": new_id("aud"), "merchant_id": merchant_id, "action": action, "target": target, "detail": detail, "actor": actor.get() or {"kind": "system"}, "created_at": datetime.now(UTC)}
    )


def payout_detail(payout: dict) -> dict:
    return {"method": payout["method"], "currency": payout["currency"], "total_cents": payout["total_cents"], "affiliates": len(payout["items"]), "reference": payout.get("reference")}
