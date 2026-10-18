from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..config import get_settings
from ..ids import new_id, random_id, sha256
from ..security import MAX_PROGRAMS, check_password, client_ip_hash, db_dep, email_verified, hash_password, issue_token, public_user, selected_merchant, signed_in_user
from ..services.notify import account_email

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


async def _session(db, user: dict, request: Request) -> dict:
    # Remember recent sign-in IPs (hashed) for self-referral checks.
    await db.users.update_one({"_id": user["_id"]}, {"$push": {"ip_hashes": {"$each": [client_ip_hash(request)], "$slice": -10}}})
    return {"token": issue_token(user), "user": public_user(user)}


@router.post("/signup")
async def signup(body: SignupIn, request: Request, db=Depends(db_dep)):
    user = {
        "_id": new_id("usr"),
        "email": body.email.lower(),
        "name": body.name.strip(),
        "password_hash": hash_password(body.password),
        "ip_hashes": [],
        "email_verified": False,
        "created_at": datetime.now(UTC),
    }
    try:
        await db.users.insert_one(user)
    except DuplicateKeyError:
        if await db.users.find_one({"email": user["email"], "password_hash": {"$exists": False}}):
            raise HTTPException(409, "you were invited to an affiliate program with this email. Use the link in that email to set your password")
        raise HTTPException(409, "an account with that email already exists. Sign in, or reset your password")
    await _send_verification(db, user, _safe_next(body.next), body.site)
    return await _session(db, user, request)


@router.post("/login")
async def login(body: LoginIn, request: Request, db=Depends(db_dep)):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not user.get("password_hash") or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "wrong email or password")
    return await _session(db, user, request)


@router.get("/me")
async def me(request: Request, user=Depends(signed_in_user), db=Depends(db_dep)):
    fields = {"_id": 1, "name": 1, "slug": 1}
    merchant = await selected_merchant(db, user["_id"], request.headers.get("x-kickrail-program"), fields)
    programs = await db.merchants.find({"member_ids": user["_id"]}, fields).sort("created_at", 1).to_list(MAX_PROGRAMS * 3)
    affiliations = await db.affiliates.count_documents({"user_id": user["_id"]})
    out = lambda m: {"id": m["_id"], "name": m["name"], "slug": m["slug"]}  # noqa: E731
    return {
        "user": public_user(user),
        "merchant": out(merchant) if merchant else None,
        "merchants": [out(m) for m in programs],
        "affiliations": affiliations,
    }


class ClaimIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=100)


@router.post("/claim")
async def claim(body: ClaimIn, request: Request, db=Depends(db_dep)):
    """Set a password on an account a merchant created through the API."""
    # The claim link was emailed to this address, so using it proves the address.
    s = {"password_hash": hash_password(body.password), "claimed_at": datetime.now(UTC), "email_verified": True} | ({"name": body.name.strip()} if body.name and body.name.strip() else {})
    user = await db.users.find_one_and_update(
        {"claim_token_hash": sha256(body.token), "password_hash": {"$exists": False}}, {"$set": s, "$unset": {"claim_token_hash": ""}}, return_document=ReturnDocument.AFTER
    )
    if not user:
        raise HTTPException(400, "this link was already used or is invalid")
    return await _session(db, user, request)


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


async def _send_verification(db, user: dict, next: str | None, site: str | None = None) -> None:
    token = random_id(40)
    now = datetime.now(UTC)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"verify_token_hash": sha256(token), "verify_expires_at": now + VERIFY_TTL, "verify_sent_at": now, "verify_next": next}})
    url = f"{await _link_base(db, site)}/verify?token={token}"
    await account_email(
        db, user["email"], "verify_email", "Confirm your email for Kickrail", "Confirm your email",
        [f"Hi {user.get('name') or 'there'}, confirm this is your address to finish setting up your Kickrail account.", "The link works for 3 days. If you didn't sign up, ignore this email and nothing happens."],
        ("Confirm email", url),
    )


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)


@router.post("/verify")
async def verify(body: TokenIn, db=Depends(db_dep)):
    user = await db.users.find_one_and_update(
        {"verify_token_hash": sha256(body.token), "verify_expires_at": {"$gt": datetime.now(UTC)}},
        {"$set": {"email_verified": True, "email_verified_at": datetime.now(UTC)}, "$unset": {"verify_token_hash": "", "verify_expires_at": ""}},
    )
    if not user:
        raise HTTPException(400, "this link has expired or was already used. Sign in and we'll send a new one")
    return {"ok": True, "email": user["email"], "next": user.get("verify_next")}


class ResendIn(BaseModel):
    next: str | None = Field(default=None, max_length=300)
    site: str | None = Field(default=None, max_length=300)


@router.post("/verify/resend")
async def resend_verification(body: ResendIn, user=Depends(signed_in_user), db=Depends(db_dep)):
    if email_verified(user):
        return {"ok": True, "already_verified": True}
    if _recent(user.get("verify_sent_at")):
        raise HTTPException(429, "we just sent one. Give it a minute, and check spam")
    await _send_verification(db, user, _safe_next(body.next) or user.get("verify_next"), body.site)
    return {"ok": True}


class ForgotIn(BaseModel):
    email: EmailStr
    site: str | None = Field(default=None, max_length=300)


@router.post("/password/forgot")
async def forgot_password(body: ForgotIn, db=Depends(db_dep)):
    """Always answers the same way, so it can't be used to find out who has an account."""
    user = await db.users.find_one({"email": body.email.lower()})
    if user and not _recent(user.get("reset_sent_at")):
        token = random_id(40)
        now = datetime.now(UTC)
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"reset_token_hash": sha256(token), "reset_expires_at": now + RESET_TTL, "reset_sent_at": now}})
        await account_email(
            db, user["email"], "password_reset", "Reset your Kickrail password", "Reset your password",
            ["Someone asked to reset the password for this Kickrail account. If it was you, use the button below. The link works for 1 hour.", "If it wasn't you, ignore this email. Your password stays the same."],
            ("Choose a new password", f"{await _link_base(db, body.site)}/reset?token={quote(token)}"),
        )
    return {"ok": True}


class ResetIn(TokenIn):
    password: str = Field(min_length=8, max_length=200)


@router.post("/password/reset")
async def reset_password(body: ResetIn, request: Request, db=Depends(db_dep)):
    now = datetime.now(UTC)
    user = await db.users.find_one_and_update(
        {"reset_token_hash": sha256(body.token), "reset_expires_at": {"$gt": now}},
        {
            # The link came by email, so the address is proven too. Older sessions stop working.
            "$set": {"password_hash": hash_password(body.password), "email_verified": True},
            "$inc": {"session_gen": 1},
            "$unset": {"reset_token_hash": "", "reset_expires_at": "", "claim_token_hash": "", "verify_token_hash": "", "verify_expires_at": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not user:
        raise HTTPException(400, "this link has expired or was already used. Ask for a new one")
    return await _session(db, user, request)


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
    return {"email": inv["email"], "merchant": {"name": m["name"], "slug": m["slug"]}, "invited_by": (inviter or {}).get("name", ""), "has_account": bool(await db.users.find_one({"email": inv["email"], "password_hash": {"$exists": True}}))}


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
