from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Request
from pymongo.asynchronous.database import AsyncDatabase

from .config import get_settings
from .db import get_db
from .ids import hash_ip, sha256

SESSION_DAYS = 30


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(11)).decode()


def check_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def issue_token(user: dict) -> str:
    now = datetime.now(UTC)
    # "gen" ties the session to the user's current generation; a password reset bumps it.
    return jwt.encode({"sub": user["_id"], "gen": user.get("session_gen", 0), "iat": now, "exp": now + timedelta(days=SESSION_DAYS)}, get_settings().app_secret, algorithm="HS256")


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


async def signed_in_user(authorization: str = Header(default=""), db: AsyncDatabase = Depends(db_dep)) -> dict:
    """Any valid session, verified or not. Only the verify and invite flows use this directly."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token.startswith("sk_kr_"):
        raise HTTPException(401, "not signed in")
    try:
        payload = jwt.decode(token, get_settings().app_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "session expired")
    user = await db.users.find_one({"_id": payload["sub"]})
    # A password reset signs out every session issued before it.
    if not user or payload.get("gen", 0) != user.get("session_gen", 0):
        raise HTTPException(401, "not signed in")
    return user


async def current_user(user: dict = Depends(signed_in_user)) -> dict:
    if not email_verified(user):
        raise HTTPException(403, UNVERIFIED)
    return user


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
    return merchant


async def api_merchant(authorization: str = Header(default=""), db: AsyncDatabase = Depends(db_dep)) -> dict:
    """Merchant server API: Authorization: Bearer sk_kr_..."""
    key = authorization.removeprefix("Bearer ").strip()
    if not key.startswith("sk_kr_"):
        raise HTTPException(401, "expected a Kickrail secret key (sk_kr_...)")
    merchant = await db.merchants.find_one({"secret_key_hash": sha256(key)})
    if not merchant:
        raise HTTPException(401, "unknown secret key")
    return merchant


def public_user(u: dict) -> dict:
    return {"id": u["_id"], "email": u["email"], "name": u.get("name", ""), "payouts_enabled": bool(u.get("payouts_enabled")), "can_be_paid": can_be_paid(u), "email_verified": email_verified(u)}


def can_be_paid(u: dict) -> bool:
    """A program can pay this person: saved manual details or a ready Stripe account."""
    return bool(u.get("payout_details") or u.get("payouts_enabled"))
