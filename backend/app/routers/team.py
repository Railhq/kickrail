"""Workspace members. Everyone in member_ids can run the program; only the owner
can remove people or download tax IDs."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from .. import plans
from ..config import get_settings
from ..db import run_in_transaction
from ..ids import new_id, random_id, sha256
from ..security import current_merchant, current_user, db_dep
from ..services import audit, notify

router = APIRouter(prefix="/merchant/team", tags=["team"])

INVITE_DAYS = 7


@router.get("")
async def team(m=Depends(current_merchant), db=Depends(db_dep)):
    users = await db.users.find({"_id": {"$in": m.get("member_ids", [])}}).to_list(None)
    invites = await db.invites.find({"merchant_id": m["_id"], "accepted_at": {"$exists": False}, "revoked_at": {"$exists": False}, "expires_at": {"$gt": datetime.now(UTC)}}).sort("created_at", -1).to_list(None)
    return {
        "owner_id": m.get("owner_id"),
        "members": [{"id": u["_id"], "name": u.get("name", ""), "email": u["email"], "owner": u["_id"] == m.get("owner_id")} for u in users],
        "invites": [{"id": i["_id"], "email": i["email"], "created_at": i["created_at"], "expires_at": i["expires_at"]} for i in invites],
    }


class InviteIn(BaseModel):
    email: EmailStr


@router.post("/invites")
async def invite(body: InviteIn, m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep)):
    email = body.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing and existing["_id"] in m.get("member_ids", []):
        raise HTTPException(409, "they're already on the team")
    open_invites = await db.invites.count_documents({"merchant_id": m["_id"], "email": {"$ne": email}, "accepted_at": {"$exists": False}, "revoked_at": {"$exists": False}, "expires_at": {"$gt": datetime.now(UTC)}})
    plans.require_room(m, "teammates", len(m.get("member_ids") or []) + open_invites)
    if await db.invites.count_documents({"merchant_id": m["_id"], "created_at": {"$gt": datetime.now(UTC) - timedelta(days=1)}}) >= 20:
        raise HTTPException(429, "too many invites today")
    token = random_id(32)
    now = datetime.now(UTC)
    # A new invite replaces any open one for the same email.
    inv = {"_id": new_id("inv"), "merchant_id": m["_id"], "email": email, "token_hash": sha256(token), "invited_by": user["_id"], "created_at": now, "expires_at": now + timedelta(days=INVITE_DAYS)}
    url = f"{get_settings().public_url}/invite/{token}"
    text, html = notify.render(
        m, f"Join {m['name']} on Kickrail",
        [f"{user.get('name') or user['email']} invited you to help run the {m['name']} affiliate program.", f"The link works for {INVITE_DAYS} days and only for {email}."],
        ("Accept the invite", url),
    )
    from ..services.outbox import queue_email


    async def invite(tdb):
        await tdb.invites.update_many({"merchant_id": m["_id"], "email": email, "accepted_at": {"$exists": False}}, {"$set": {"revoked_at": now}})
        await tdb.invites.insert_one(inv)
        await queue_email(tdb, email, f"{user.get('name') or 'A teammate'} invited you to {m['name']} on Kickrail", text, html, kind="team_invite", merchant_id=m["_id"], reply_to=user["email"])

    await run_in_transaction(db, invite)
    return {"id": inv["_id"], "email": email, "created_at": now, "expires_at": inv["expires_at"]}


@router.delete("/invites/{invite_id}")
async def revoke(invite_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    res = await db.invites.update_one({"_id": invite_id, "merchant_id": m["_id"], "accepted_at": {"$exists": False}}, {"$set": {"revoked_at": datetime.now(UTC)}})
    if not res.matched_count:
        raise HTTPException(404, "invite not found")
    return {"ok": True}


@router.delete("/members/{user_id}")
async def remove(user_id: str, m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep)):
    if user_id == m.get("owner_id"):
        raise HTTPException(400, "the owner can't be removed")
    if user["_id"] != m.get("owner_id") and user["_id"] != user_id:
        raise HTTPException(403, "only the owner can remove other members")
    res = await db.merchants.update_one({"_id": m["_id"], "member_ids": user_id}, {"$pull": {"member_ids": user_id}})
    if not res.modified_count:
        raise HTTPException(404, "not a member")
    return {"ok": True}


class OwnerIn(BaseModel):
    user_id: str


@router.post("/owner")
async def transfer_owner(body: OwnerIn, m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep)):
    """Hands the program to another member. The old owner stays on the team."""
    if user["_id"] != m.get("owner_id"):
        raise HTTPException(403, "only the owner can hand over ownership")
    if body.user_id == m.get("owner_id"):
        raise HTTPException(400, "they already own this program")

    async def move(tdb) -> bool:
        # The Railhq Pass lift belongs to whoever owns the program.
        heir = await tdb.users.find_one({"_id": body.user_id}, {"railhq_pass": 1}) or {}
        res = await tdb.merchants.update_one({"_id": m["_id"], "owner_id": user["_id"], "member_ids": body.user_id}, {"$set": {"owner_id": body.user_id, "railhq_pass": bool(heir.get("railhq_pass"))}})
        if not res.modified_count:
            return False
        await audit.record(tdb, m["_id"], "team.owner_changed", body.user_id, previous_owner=user["_id"])
        return True

    if not await run_in_transaction(db, move):
        raise HTTPException(404, "not a member")
    return {"ok": True}
