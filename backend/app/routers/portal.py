"""Affiliate side. One Kickrail account works across every program the user joins."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from ..config import get_settings
from ..crypto import encrypt
from ..deps import merchant_api_factory, platform_api
from ..security import client_ip_hash, current_user, db_dep, public_user
from ..services.affiliates import AffiliateError, add_link, affiliate_view, create_affiliate, pipeline, program_public
from ..services import terms
from .merchant import out

router = APIRouter(tags=["portal"])


@router.get("/programs/{slug}")
async def program(slug: str, db=Depends(db_dep)):
    m = await db.merchants.find_one({"slug": slug})
    if not m:
        raise HTTPException(404, "program not found")
    campaign = await db.campaigns.find_one({"merchant_id": m["_id"], "is_default": True})
    return program_public(m, campaign)


@router.get("/programs/{slug}/terms")
async def program_terms(slug: str, db=Depends(db_dep)):
    m = await db.merchants.find_one({"slug": slug})
    if not m or not m.get("terms"):
        raise HTTPException(404, "no terms")
    return {"program": program_public(m, None), "terms": terms.public(m)}


async def _public_campaign(db, m: dict, campaign_slug: str) -> dict:
    """A campaign people can join on their own: public, or the default one."""
    c = await db.campaigns.find_one({"merchant_id": m["_id"], "slug": campaign_slug.lower()})
    if not c or not (c.get("public") or c.get("is_default")):
        raise HTTPException(404, "campaign not found")
    return c


@router.get("/programs/{slug}/campaigns/{campaign_slug}")
async def campaign_page(slug: str, campaign_slug: str, db=Depends(db_dep)):
    m = await db.merchants.find_one({"slug": slug})
    if not m:
        raise HTTPException(404, "program not found")
    return program_public(m, await _public_campaign(db, m, campaign_slug))


class JoinIn(BaseModel):
    campaign: str | None = Field(default=None, max_length=40)


@router.post("/programs/{slug}/join")
async def join(slug: str, body: JoinIn | None = None, user=Depends(current_user), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    m = await db.merchants.find_one({"slug": slug})
    if not m:
        raise HTTPException(404, "program not found")
    campaign_id = (await _public_campaign(db, m, body.campaign))["_id"] if body and body.campaign else None
    try:
        aff, _ = await create_affiliate(db, m, user, factory, campaign_id=campaign_id)
    except AffiliateError as e:
        raise HTTPException(e.status, str(e))
    return out(aff)


@router.get("/portal")
async def portal(user=Depends(current_user), db=Depends(db_dep)):
    affs = await db.affiliates.find({"user_id": user["_id"]}).sort("created_at", -1).to_list(None)
    merchants = {m["_id"]: m async for m in db.merchants.find({"_id": {"$in": [a["merchant_id"] for a in affs]}})}
    programs = []
    for a in affs:
        m = merchants[a["merchant_id"]]
        p = await pipeline(db, a)
        programs.append(
            {
                "affiliate_id": a["_id"],
                "status": a["status"],
                "program": {"slug": m["slug"], "name": m["name"], "logo_url": (m.get("branding") or {}).get("logo_url"), "color": (m.get("branding") or {}).get("color")},
                "clicks": p["clicks"],
                "customers": p["customers"],
                "totals": p["totals"],
            }
        )
    return {"user": public_user(user), "programs": programs}


async def _own(db, affiliate_id: str, user: dict) -> tuple[dict, dict]:
    aff = await db.affiliates.find_one({"_id": affiliate_id, "user_id": user["_id"]})
    if not aff:
        raise HTTPException(404, "not found")
    return aff, await db.merchants.find_one({"_id": aff["merchant_id"]})


@router.get("/portal/{affiliate_id}")
async def program_detail(affiliate_id: str, user=Depends(current_user), db=Depends(db_dep)):
    aff, m = await _own(db, affiliate_id, user)
    return await affiliate_view(db, m, aff, user)


class LinkIn(BaseModel):
    token: str = Field(min_length=3, max_length=32)
    landing_url: str | None = Field(default=None, max_length=1000)
    label: str = Field(default="", max_length=80)


@router.post("/portal/{affiliate_id}/links")
async def add_own_link(affiliate_id: str, body: LinkIn, user=Depends(current_user), db=Depends(db_dep)):
    aff, m = await _own(db, affiliate_id, user)
    if not m["settings"].get("affiliate_links", True):
        raise HTTPException(403, "this program doesn't let affiliates add links")
    try:
        return await add_link(db, m, aff, body.token, body.landing_url, body.label)
    except AffiliateError as e:
        raise HTTPException(e.status, str(e))


@router.delete("/portal/{affiliate_id}/links/{link_id}")
async def delete_own_link(affiliate_id: str, link_id: str, user=Depends(current_user), db=Depends(db_dep)):
    aff, _ = await _own(db, affiliate_id, user)
    res = await db.affiliate_links.delete_one({"_id": link_id, "affiliate_id": aff["_id"]})
    if not res.deleted_count:
        raise HTTPException(404, "link not found")
    return {"ok": True}


class TokenIn(BaseModel):
    token: str = Field(pattern=r"^[a-z0-9_-]{3,32}$")


@router.put("/portal/{affiliate_id}/token")
async def change_token(affiliate_id: str, body: TokenIn, user=Depends(current_user), db=Depends(db_dep)):
    """Old links keep working only through existing cookies; new clicks need the new token."""
    aff, m = await _own(db, affiliate_id, user)
    if body.token != aff["token"] and await db.affiliate_links.find_one({"merchant_id": m["_id"], "token": body.token}):
        raise HTTPException(409, "that link name is taken in this program")
    try:
        await db.affiliates.update_one({"_id": aff["_id"]}, {"$set": {"token": body.token}})
    except DuplicateKeyError:
        raise HTTPException(409, "that link name is taken in this program")
    return {"ok": True}


# ---------- payout account (Stripe Connect Express on the Kickrail platform) ----------


class OnboardIn(BaseModel):
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")


@router.post("/payout-account/onboard")
async def onboard(body: OnboardIn, user=Depends(current_user), db=Depends(db_dep), platform=Depends(platform_api)):
    acct = user.get("connect_account_id")
    if not acct:
        acct = await platform.create_express_account(user["email"], user["_id"], body.country)
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"connect_account_id": acct}})
    base = get_settings().public_url
    url = await platform.onboarding_link(acct, f"{base}/a/payouts?refresh=1", f"{base}/a/payouts?done=1")
    return {"url": url}


class PayoutDetailsIn(BaseModel):
    method: Literal["paypal", "wise", "bank", "other"]
    value: str = Field(min_length=3, max_length=500)


@router.get("/payout-account")
async def payout_account(user=Depends(current_user)):
    """Saved state only, no Stripe call: works when Stripe payouts aren't configured."""
    return {"details": user.get("payout_details"), "connected": bool(user.get("connect_account_id")), "payouts_enabled": bool(user.get("payouts_enabled")), "stripe_payouts": get_settings().stripe_payouts}


@router.put("/payout-account/details")
async def save_payout_details(body: PayoutDetailsIn, user=Depends(current_user), db=Depends(db_dep)):
    details = {"method": body.method, "value": body.value.strip(), "updated_at": datetime.now(UTC)}
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"payout_details": details}})
    return {"details": details}


@router.post("/payout-account/refresh")
async def refresh(user=Depends(current_user), db=Depends(db_dep), platform=Depends(platform_api)):
    if not user.get("connect_account_id"):
        return {"payouts_enabled": False, "connected": False, "state": "not_connected"}
    state = await platform.payout_status(user["connect_account_id"])
    enabled = state == "ready"
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"payouts_enabled": enabled}})
    return {"payouts_enabled": enabled, "connected": True, "state": state}


@router.post("/payout-account/dashboard")
async def express_dashboard(user=Depends(current_user), platform=Depends(platform_api)):
    if not user.get("connect_account_id"):
        raise HTTPException(400, "set up payouts first")
    return {"url": await platform.dashboard_link(user["connect_account_id"])}


# ---------- tax form (W-9 for US persons, W-8BEN / W-8BEN-E for everyone else) ----------


class TaxInfoIn(BaseModel):
    form: Literal["w9", "w8ben", "w8bene"]
    legal_name: str = Field(min_length=2, max_length=120)
    business_name: str = Field(default="", max_length=120)
    # W-9 federal tax classification; W-8 forms ignore it.
    classification: Literal["individual", "c_corp", "s_corp", "partnership", "trust", "llc", "other"] = "individual"
    country: str = Field(pattern=r"^[A-Z]{2}$", description="citizenship (W-8BEN) or country of organisation")
    address: str = Field(min_length=5, max_length=400)
    tin: str = Field(min_length=4, max_length=40, description="SSN/EIN for a W-9, foreign TIN for a W-8")
    date_of_birth: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    treaty_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    signature: str = Field(min_length=2, max_length=120)
    certify: bool


def tax_public(t: dict | None) -> dict | None:
    if not t:
        return None
    return {k: t.get(k) for k in ("form", "legal_name", "business_name", "classification", "country", "address", "date_of_birth", "treaty_country", "signature", "signed_at")} | {"tin_last4": t["tin_last4"]}


@router.get("/tax-info")
async def get_tax_info(user=Depends(current_user)):
    return {"tax_info": tax_public(user.get("tax_info"))}


@router.put("/tax-info")
async def save_tax_info(body: TaxInfoIn, request: Request, user=Depends(current_user), db=Depends(db_dep)):
    if not body.certify:
        raise HTTPException(422, "you need to certify the information under penalties of perjury")
    if (body.form == "w9") != (body.country == "US"):
        raise HTTPException(422, "use a W-9 for US persons and a W-8 form otherwise")
    tin = "".join(ch for ch in body.tin if ch.isalnum())
    if body.form == "w9" and len(tin) != 9:
        raise HTTPException(422, "an SSN or EIN has 9 digits")
    info = body.model_dump(exclude={"tin", "certify"}) | {
        "tin_enc": encrypt(tin),
        "tin_last4": tin[-4:],
        "signed_at": datetime.now(UTC),
        "signed_ip_hash": client_ip_hash(request),
    }
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"tax_info": info}})
    return {"tax_info": tax_public(info)}
