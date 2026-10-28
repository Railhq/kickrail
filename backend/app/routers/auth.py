"""Operator sign-in: the people who run programs and their teammates (users). Affiliates
have their own login in routers/partner_auth.py. With Railhq accounts switched on
(settings.railhq_enabled), the password lives at Railhq and these forms check it there,
server to server (routers/railhq.py)."""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..config import get_settings
from ..db import run_in_transaction
from ..ids import new_id, random_id, sha256
from ..railhq import RailhqError
from ..security import MAX_PROGRAMS, OPERATOR, check_password, client_ip, client_ip_hash, db_dep, email_verified, hash_password, issue_token, public_user, selected_merchant, session_claims, signed_in_user
from ..services.notify import account_email
from . import railhq

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    next: str | None = Field(default=None, max_length=300)
    site: str | None = Field(default=None, max_length=300)


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    next: str | None = Field(default=None, max_length=300)


WRONG = "wrong email or password"


async def _session(db, user: dict, request: Request, coll: str = "users", kind: str = OPERATOR, railhq_sid: str | None = None) -> dict:
    # Remember recent sign-in IPs (hashed) for self-referral checks.
    await db[coll].update_one({"_id": user["_id"]}, {"$push": {"ip_hashes": {"$each": [client_ip_hash(request)], "$slice": -10}}})
    return {"token": issue_token(user, kind, railhq_sid), "user": public_user(user)}


async def legacy_partner_only(db, user: dict | None) -> bool:
    """A users record from before the operator/partner split that only ever belonged to an
    affiliate: it was copied to partners under the same id and is only kept until the
    migration's cleanup step. It isn't an operator login."""
    if not user or await db.merchants.find_one({"member_ids": user["_id"]}, {"_id": 1}):
        return False
    return bool(await db.partners.find_one({"_id": user["_id"]}, {"_id": 1}))


async def operator_by_email(db, email: str) -> dict | None:
    user = await db.users.find_one({"email": email.lower()})
    return None if await legacy_partner_only(db, user) else user


async def drop_legacy_partner(db, email: str) -> None:
    """Make room for a new operator login on an email whose users record is an
    affiliate's leftover (their partner record is the real one)."""
    user = await db.users.find_one({"email": email.lower()})
    if await legacy_partner_only(db, user):
        await db.users.delete_one({"_id": user["_id"]})


@router.post("/signup")
async def signup(body: SignupIn, request: Request, db=Depends(db_dep)):
    email = body.email.lower()
    user = {
        "_id": new_id("usr"),
        "email": email,
        "name": body.name.strip(),
        "password_hash": hash_password(body.password),
        "ip_hashes": [],
        "email_verified": False,
        "created_at": datetime.now(UTC),
    }
    await drop_legacy_partner(db, email)
    out: dict = {}
    if railhq.enabled():
        if await db.users.find_one({"email": email}):
            raise HTTPException(409, "an account with that email already exists. Sign in, or reset your password")
        # The Railhq account holds the password and sends the confirmation email.
        try:
            got = await railhq.client().signup(email, body.password, body.name.strip(), client_ip(request))
        except RailhqError as e:
            if e.code == "exists":
                apps = ", ".join(e.body.get("apps") or [])
                raise HTTPException(409, f"you already have a Railhq account{f' (used for {apps})' if apps else ''}. Sign in with it")
            raise HTTPException(e.status if e.status in (422, 429) else 503, e.message)
        who = got["user"]
        user |= {"railhq_id": who["sub"], "railhq_pass": bool(who.get("pass")), "email_verified": bool(who.get("email_verified"))}
        user.pop("password_hash")  # Railhq holds it
        out = railhq.handoff(got["handoff"], body.next)
    try:
        await db.users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(409, "an account with that email already exists. Sign in, or reset your password")
    if not out:
        await _send_verification(db, user, _safe_next(body.next), body.site)
    return await _session(db, user, request) | out


@router.post("/login")
async def login(body: LoginIn, request: Request, db=Depends(db_dep)):
    user = await operator_by_email(db, body.email)
    if railhq.enabled():
        return await _railhq_login(db, body, user, request)
    if not user or not user.get("password_hash") or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, WRONG)
    return await _session(db, user, request)


async def _railhq_login(db, body: LoginIn, user: dict | None, request: Request) -> dict:
    """The password is Railhq's. Someone from before the switch (no railhq_id) whose old
    Kickrail password is right is moved over: their hash goes to Railhq as is."""
    if not user and await db.partners.find_one({"email": body.email.lower()}, {"_id": 1}):
        # An affiliate's email with no operator login: never sent to Railhq. The web app
        # tries the affiliate login next.
        raise HTTPException(401, WRONG)
    rh = railhq.client()
    local_ok = bool(user) and not user.get("railhq_id") and bool(user.get("password_hash")) and check_password(body.password, user["password_hash"])
    note = "This email already has a Railhq account. Next time, sign in with that password."
    try:
        got = await rh.login(body.email.lower(), body.password, client_ip(request))
    except RailhqError as e:
        if e.status == 429:
            raise HTTPException(429, "too many sign-in attempts. Wait a few minutes and try again")
        if e.status >= 500:
            if local_ok:
                return await _session(db, user, request)
            if user and user.get("railhq_id"):
                raise HTTPException(503, "Sign-in is down for a minute. Try again shortly")
            raise HTTPException(401, WRONG)
        if not local_ok:
            raise HTTPException(401, WRONG)
        if e.code != "no_account":
            # Another Railhq tool made their Railhq account, with another password.
            return await _session(db, user, request) | {"railhq_note": note}
        try:
            got = await rh.import_user(user["email"], user.get("name", ""), user["password_hash"], email_verified=user.get("email_verified") is True)
        except RailhqError as e2:
            if e2.status == 409:
                return await _session(db, user, request) | {"railhq_note": note}
            return await _session(db, user, request)
    user = await railhq.link(db, got["user"], proven=local_ok)
    return await _session(db, user, request) | railhq.handoff(got["handoff"], body.next)


@router.post("/logout")
async def logout(authorization: str = Header(default="")):
    """Where the browser goes after the web app drops the session: Railhq's sign-out, when
    the session came from a Railhq sign-in, so it ends there too."""
    try:
        claims = session_claims(authorization)
    except HTTPException:
        claims = {}
    if railhq.enabled() and claims.get("rsid"):
        return {"redirect": railhq.client().logout_url(f"{get_settings().public_url}/login")}
    return {"redirect": None}


@router.get("/me")
async def me(request: Request, user=Depends(signed_in_user), db=Depends(db_dep)):
    fields = {"_id": 1, "name": 1, "slug": 1}
    merchant = await selected_merchant(db, user["_id"], request.headers.get("x-kickrail-program"), fields)
    programs = await db.merchants.find({"member_ids": user["_id"]}, fields).sort("created_at", 1).to_list(MAX_PROGRAMS * 3)
    out = lambda m: {"id": m["_id"], "name": m["name"], "slug": m["slug"]}  # noqa: E731
    return {
        "user": public_user(user),
        "merchant": out(merchant) if merchant else None,
        "merchants": [out(m) for m in programs],
    }


# ---------- email verification and password reset ----------

VERIFY_TTL = timedelta(days=3)
RESET_TTL = timedelta(hours=1)
RESEND_GAP = timedelta(seconds=60)


def _safe_next(next: str | None) -> str | None:
    return next if next and next.startswith("/") and not next.startswith("//") else None


async def _link_base(db, site: str | None) -> str:
    """Where emailed links open: the site the request came from, when that is Kickrail
    itself or a verified portal domain, so the reader lands where they're signed in."""
    base = get_settings().public_url
    parts = urlsplit(site or "")
    if not parts.hostname or f"{parts.scheme}://{parts.netloc}" == base:
        return base
    m = await db.merchants.find_one({"portal_domains": {"$elemMatch": {"host": parts.hostname.lower(), "verified": True}}}, {"portal_domains": 1})
    if not m:
        return base
    # The domain they came from, not necessarily the program's primary one.
    local = parts.hostname.endswith(".localhost")
    return f"{'http' if local else 'https'}://{parts.hostname.lower()}{f':{parts.port}' if local and parts.port else ''}"


def _recent(sent_at: datetime | None) -> bool:
    return bool(sent_at and datetime.now(UTC) - sent_at < RESEND_GAP)


async def _send_verification(db, user: dict, next: str | None, site: str | None = None, coll: str = "users") -> None:
    token = random_id(40)
    now = datetime.now(UTC)
    url = f"{await _link_base(db, site)}/verify?token={token}"

    async def send(tdb):
        await tdb[coll].update_one({"_id": user["_id"]}, {"$set": {"verify_token_hash": sha256(token), "verify_expires_at": now + VERIFY_TTL, "verify_sent_at": now, "verify_next": next}})
        await account_email(
            tdb, user["email"], "verify_email", "Confirm your email for Kickrail", "Confirm your email",
            [f"Hi {user.get('name') or 'there'}, confirm this is your address to finish setting up your Kickrail account.", "The link works for 3 days. If you didn't sign up, ignore this email and nothing happens."],
            ("Confirm email", url),
        )

    await run_in_transaction(db, send)


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)


@router.post("/verify")
async def verify(body: TokenIn, db=Depends(db_dep)):
    return await verify_email(db, "users", body.token)


def _other(coll: str) -> str:
    return "partners" if coll == "users" else "users"


async def _not_an_operator(db, coll: str, q: dict) -> bool:
    """A link emailed before the split that belongs to an affiliate's leftover users record:
    the operator side turns it down so the web app tries the affiliate side."""
    return coll == "users" and await legacy_partner_only(db, await db.users.find_one(q))


async def verify_email(db, coll: str, token: str) -> dict:
    q = {"verify_token_hash": sha256(token), "verify_expires_at": {"$gt": datetime.now(UTC)}}
    expired = HTTPException(400, "this link has expired or was already used. Sign in and we'll send a new one")
    if await _not_an_operator(db, coll, q):
        raise expired
    change = {"$set": {"email_verified": True, "email_verified_at": datetime.now(UTC)}, "$unset": {"verify_token_hash": "", "verify_expires_at": ""}}
    user = await db[coll].find_one_and_update(q, change)
    if not user:
        raise expired
    # A link from before the split was for both logins of this email, so it confirms both.
    await db[_other(coll)].update_many({"verify_token_hash": q["verify_token_hash"]}, change)
    return {"ok": True, "email": user["email"], "next": user.get("verify_next")}


class ResendIn(BaseModel):
    next: str | None = Field(default=None, max_length=300)
    site: str | None = Field(default=None, max_length=300)


@router.post("/verify/resend")
async def resend_verification(body: ResendIn, user=Depends(signed_in_user), db=Depends(db_dep)):
    if user.get("railhq_id") and railhq.enabled() and not email_verified(user):
        # Railhq confirms the address; its user.updated event tells us when it's done.
        try:
            fresh = await railhq.client().user(user["railhq_id"])
            if fresh.get("email_verified"):
                await railhq.link(db, fresh)
                return {"ok": True, "already_verified": True}
            await railhq.client().resend_verify(user["railhq_id"])
        except RailhqError as e:
            raise HTTPException(503 if e.status >= 500 else 400, e.message)
        return {"ok": True}
    return await resend(db, "users", user, body)


async def resend(db, coll: str, user: dict, body: ResendIn) -> dict:
    if email_verified(user):
        return {"ok": True, "already_verified": True}
    if _recent(user.get("verify_sent_at")):
        raise HTTPException(429, "we just sent one. Give it a minute, and check spam")
    await _send_verification(db, user, _safe_next(body.next) or user.get("verify_next"), body.site, coll)
    return {"ok": True}


class ForgotIn(BaseModel):
    email: EmailStr
    site: str | None = Field(default=None, max_length=300)


@router.post("/password/forgot")
async def forgot_password(body: ForgotIn, db=Depends(db_dep)):
    """Always answers the same way, so it can't be used to find out who has an account."""
    user = await operator_by_email(db, body.email)
    if railhq.enabled() and (user.get("railhq_id") if user else not await db.partners.find_one({"email": body.email.lower()}, {"_id": 1})):
        # Railhq holds the password (or may: someone who signed up in another Railhq tool).
        # An affiliate's email is never sent there.
        try:
            await railhq.client().forgot(body.email.lower())
        except RailhqError as e:
            log.warning("railhq forgot failed: %s", e.message)
        return {"ok": True}
    return await send_reset(db, "users", user, body.site)


async def send_reset(db, coll: str, user: dict | None, site: str | None) -> dict:
    if user and not _recent(user.get("reset_sent_at")):
        token = random_id(40)
        now = datetime.now(UTC)
        url = f"{await _link_base(db, site)}/reset?token={quote(token)}"

        async def send(tdb):
            await tdb[coll].update_one({"_id": user["_id"]}, {"$set": {"reset_token_hash": sha256(token), "reset_expires_at": now + RESET_TTL, "reset_sent_at": now}})
            await account_email(
                tdb, user["email"], "password_reset", "Reset your Kickrail password", "Reset your password",
                ["Someone asked to reset the password for this Kickrail account. If it was you, use the button below. The link works for 1 hour.", "If it wasn't you, ignore this email. Your password stays the same."],
                ("Choose a new password", url),
            )

        await run_in_transaction(db, send)
    return {"ok": True}


class ResetIn(TokenIn):
    password: str = Field(min_length=8, max_length=200)


@router.post("/password/reset")
async def reset_password(body: ResetIn, request: Request, db=Depends(db_dep)):
    return await reset(db, "users", body, request, OPERATOR)


async def reset(db, coll: str, body: ResetIn, request: Request, kind: str) -> dict:
    now = datetime.now(UTC)
    q = {"reset_token_hash": sha256(body.token), "reset_expires_at": {"$gt": now}}
    expired = HTTPException(400, "this link has expired or was already used. Ask for a new one")
    if await _not_an_operator(db, coll, q):
        raise expired
    change = {
        # The link came by email, so the address is proven too. Older sessions stop working.
        "$set": {"password_hash": hash_password(body.password), "email_verified": True},
        "$inc": {"session_gen": 1},
        "$unset": {"reset_token_hash": "", "reset_expires_at": "", "claim_token_hash": "", "verify_token_hash": "", "verify_expires_at": ""},
    }
    user = await db[coll].find_one_and_update(q, change, return_document=ReturnDocument.AFTER)
    if not user:
        raise expired
    # A link from before the split reset the one password both logins of this email shared,
    # so it sets both, as it would have then.
    await db[_other(coll)].update_many({"reset_token_hash": q["reset_token_hash"]}, change)
    return await _session(db, user, request, coll, kind)


# ---------- team invites ----------


async def _invite(db, token: str) -> tuple[dict, dict]:
    inv = await db.invites.find_one({"token_hash": sha256(token), "accepted_at": {"$exists": False}, "revoked_at": {"$exists": False}})
    m = await db.merchants.find_one({"_id": inv["merchant_id"]}) if inv else None
    if not inv or not m or inv["expires_at"] < datetime.now(UTC):
        raise HTTPException(404, "this invite was used, revoked or has expired")
    return inv, m


@router.get("/invites/{token}")
async def get_invite(token: str, db=Depends(db_dep)):
    inv, m = await _invite(db, token)
    inviter = await db.users.find_one({"_id": inv["invited_by"]}, {"name": 1})
    return {"email": inv["email"], "merchant": {"name": m["name"], "slug": m["slug"]}, "invited_by": (inviter or {}).get("name", ""), "has_account": bool((await operator_by_email(db, inv["email"]) or {}).get("password_hash") or (await operator_by_email(db, inv["email"]) or {}).get("railhq_id"))}


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, user=Depends(signed_in_user), db=Depends(db_dep)):
    inv, m = await _invite(db, token)
    if user["email"] != inv["email"]:
        raise HTTPException(403, f"this invite is for {inv['email']}. Sign in with that email to accept it")
    if not email_verified(user):
        # The invite went to this address, so holding its token proves the address.
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"email_verified": True}, "$unset": {"verify_token_hash": "", "verify_expires_at": ""}})
    await db.merchants.update_one({"_id": m["_id"]}, {"$addToSet": {"member_ids": user["_id"]}})
    await db.invites.update_one({"_id": inv["_id"]}, {"$set": {"accepted_at": datetime.now(UTC), "user_id": user["_id"]}})
    return {"ok": True, "merchant": {"id": m["_id"], "name": m["name"]}}
