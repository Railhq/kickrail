"""Affiliate (partner) sign-in, on each program's portal. A partner is one person across
every program they promote (affiliates.user_id is a partner id). Separate from the
operator login in routers/auth.py, even for the same email, and never through Railhq.

The emails and links are the ones affiliates always got; only where they land changed."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..ids import new_id, sha256
from ..security import PARTNER, check_password, db_dep, hash_password, public_user, signed_in_partner
from .auth import WRONG, ForgotIn, LoginIn, ResendIn, ResetIn, SignupIn, TokenIn, _safe_next, _send_verification, _session, resend, reset, send_reset, verify_email

router = APIRouter(prefix="/partner/auth", tags=["partner auth"])
P = "partners"


async def _start(db, partner: dict, request: Request) -> dict:
    return await _session(db, partner, request, P, PARTNER)


@router.post("/signup")
async def signup(body: SignupIn, request: Request, db=Depends(db_dep)):
    partner = {
        "_id": new_id("ptn"),
        "email": body.email.lower(),
        "name": body.name.strip(),
        "password_hash": hash_password(body.password),
        "ip_hashes": [],
        "email_verified": False,
        "created_at": datetime.now(UTC),
    }
    try:
        await db.partners.insert_one(partner)
    except DuplicateKeyError:
        if await db.partners.find_one({"email": partner["email"], "password_hash": {"$exists": False}}):
            raise HTTPException(409, "you were invited to an affiliate program with this email. Use the link in that email to set your password")
        raise HTTPException(409, "an account with that email already exists. Sign in, or reset your password")
    await _send_verification(db, partner, _safe_next(body.next), body.site, P)
    return await _start(db, partner, request)


@router.post("/login")
async def login(body: LoginIn, request: Request, db=Depends(db_dep)):
    partner = await db.partners.find_one({"email": body.email.lower()})
    if not partner or not partner.get("password_hash") or not check_password(body.password, partner["password_hash"]):
        raise HTTPException(401, WRONG)
    return await _start(db, partner, request)


@router.get("/me")
async def me(partner=Depends(signed_in_partner), db=Depends(db_dep)):
    return {"user": public_user(partner), "affiliations": await db.affiliates.count_documents({"user_id": partner["_id"]})}


class ClaimIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=100)


@router.post("/claim")
async def claim(body: ClaimIn, request: Request, db=Depends(db_dep)):
    """Set a password on an account a merchant created (dashboard, API or an import)."""
    # The claim link was emailed to this address, so using it proves the address.
    s = {"password_hash": hash_password(body.password), "claimed_at": datetime.now(UTC), "email_verified": True} | ({"name": body.name.strip()} if body.name and body.name.strip() else {})
    partner = await db.partners.find_one_and_update(
        {"claim_token_hash": sha256(body.token), "password_hash": {"$exists": False}}, {"$set": s, "$unset": {"claim_token_hash": ""}}, return_document=ReturnDocument.AFTER
    )
    if not partner:
        raise HTTPException(400, "this link was already used or is invalid")
    return await _start(db, partner, request)


@router.post("/verify")
async def verify(body: TokenIn, db=Depends(db_dep)):
    return await verify_email(db, P, body.token)


@router.post("/verify/resend")
async def resend_verification(body: ResendIn, partner=Depends(signed_in_partner), db=Depends(db_dep)):
    return await resend(db, P, partner, body)


@router.post("/password/forgot")
async def forgot_password(body: ForgotIn, db=Depends(db_dep)):
    """Always answers the same way, so it can't be used to find out who has an account."""
    return await send_reset(db, P, await db.partners.find_one({"email": body.email.lower()}), body.site)


@router.post("/password/reset")
async def reset_password(body: ResetIn, request: Request, db=Depends(db_dep)):
    return await reset(db, P, body, request, PARTNER)
