from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Request
from pymongo.asynchronous.database import AsyncDatabase

from .config import get_settings
from .db import get_db
from .ids import hash_ip, sha256
from .services import audit

SESSION_DAYS = 30


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(11)).decode()


def check_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


# Who a session is for: someone who runs programs (users) or an affiliate (partners). The
# two are separate logins, even for one email. Sessions from before the split carry no
# kind and were made from the one users record, which the migration copied to partners
# under the same id, so they keep working on both sides until they expire.
OPERATOR, PARTNER = "op", "pt"


def issue_token(user: dict, kind: str = OPERATOR, railhq_sid: str | None = None) -> str:
    """A session. One made from a Railhq sign-in carries that session's id, so signing out
    of Railhq (back-channel logout) ends it here too."""
    now = datetime.now(UTC)
    # "gen" ties the session to the user's current generation; a password reset bumps it.
    claims = {"sub": user["_id"], "k": kind, "gen": user.get("session_gen", 0), "iat": now, "exp": now + timedelta(days=SESSION_DAYS)}
    if railhq_sid:
        claims["rsid"] = railhq_sid
    return jwt.encode(claims, get_settings().app_secret, algorithm="HS256")


def issue_partner_token(partner: dict) -> str:
    return issue_token(partner, PARTNER)


def client_ip(request: Request) -> str:
    # Only the web proxy can reach us (internal token), so its X-Forwarded-For is trusted.
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "0.0.0.0")


def client_ip_hash(request: Request) -> str:
    return hash_ip(client_ip(request))


async def db_dep() -> AsyncDatabase:
    return await get_db()


UNVERIFIED = "verify your email address first. We sent you a link"


def email_verified(u: dict) -> bool:
    # Accounts from before verification existed have no flag and count as verified.
    return u.get("email_verified", True)


def session_claims(authorization: str) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token.startswith("sk_kr_"):
        raise HTTPException(401, "not signed in")
    try:
        return jwt.decode(token, get_settings().app_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "session expired")


async def _holder(db: AsyncDatabase, coll: str, payload: dict) -> dict:
    user = await db[coll].find_one({"_id": payload["sub"]})
    # A password reset signs out every session issued before it.
    if not user or payload.get("gen", 0) != user.get("session_gen", 0):
        raise HTTPException(401, "not signed in")
    return user


async def signed_in_user(authorization: str = Header(default=""), db: AsyncDatabase = Depends(db_dep)) -> dict:
    """Any valid operator session, verified or not. Only the verify and invite flows use this directly."""
    payload = session_claims(authorization)
    if payload.get("k", OPERATOR) != OPERATOR:
        raise HTTPException(401, "not signed in")
    user = await _holder(db, "users", payload)
    # Signed out at Railhq (back-channel logout), for one session or all of them.
    out = user.get("signed_out_at")
    if out and payload.get("iat", 0) < int(out.timestamp()):
        raise HTTPException(401, "session expired")
    if payload.get("rsid") and await db.railhq_signouts.find_one({"_id": payload["rsid"]}):
        raise HTTPException(401, "signed out")
    return user


async def signed_in_partner(authorization: str = Header(default=""), db: AsyncDatabase = Depends(db_dep)) -> dict:
    """Any valid affiliate session, verified or not."""
    payload = session_claims(authorization)
    if payload.get("k", PARTNER) != PARTNER:
        raise HTTPException(401, "not signed in")
    return await _holder(db, "partners", payload)


async def current_user(user: dict = Depends(signed_in_user)) -> dict:
    if not email_verified(user):
        raise HTTPException(403, UNVERIFIED)
    return user


async def current_partner(partner: dict = Depends(signed_in_partner)) -> dict:
    if not email_verified(partner):
        raise HTTPException(403, UNVERIFIED)
    return partner


MAX_PROGRAMS = 10  # programs one account can create


async def selected_merchant(db: AsyncDatabase, user_id: str, wanted: str | None, projection: dict | None = None) -> dict | None:
    """The program the dashboard is on. An account can run several programs; the web app
    sends the chosen one's id in X-Kickrail-Program and it counts only if the user is a
    member. Otherwise it's their oldest program."""
    if wanted:
        merchant = await db.merchants.find_one({"_id": wanted, "member_ids": user_id}, projection)
        if merchant:
            return merchant
    return await db.merchants.find_one({"member_ids": user_id}, projection, sort=[("created_at", 1)])


async def current_merchant(request: Request, user: dict = Depends(current_user), db: AsyncDatabase = Depends(db_dep)) -> dict:
    merchant = await selected_merchant(db, user["_id"], request.headers.get("x-kickrail-program"))
    if not merchant:
        raise HTTPException(404, "no merchant workspace")
    audit.as_user(user)
    return merchant


async def api_merchant(authorization: str = Header(default=""), db: AsyncDatabase = Depends(db_dep)) -> dict:
    """Merchant server API: Authorization: Bearer sk_kr_..."""
    key = authorization.removeprefix("Bearer ").strip()
    if not key.startswith("sk_kr_"):
        raise HTTPException(401, "expected a Kickrail secret key (sk_kr_...)")
    merchant = await db.merchants.find_one({"secret_key_hash": sha256(key)})
    if not merchant:
        raise HTTPException(401, "unknown secret key")
    audit.actor.set({"kind": "api_key"})
    return merchant


def public_user(u: dict) -> dict:
    """An operator or a partner, the same shape for both."""
    return {"id": u["_id"], "email": u["email"], "name": u.get("name", ""), "payouts_enabled": bool(u.get("payouts_enabled")), "can_be_paid": can_be_paid(u), "email_verified": email_verified(u)}


def can_be_paid(u: dict) -> bool:
    """A program can pay this person: saved manual details or a ready Stripe account."""
    return bool(u.get("payout_details") or u.get("payouts_enabled"))
