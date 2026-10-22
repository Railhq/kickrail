"""Merchant server API, authenticated with the secret key (sk_kr_...).

The reliable attribution path: on signup, your backend reports who signed up and
the kr_ref cookie it saw. Server to server, so ad blockers and Safari's cookie
limits never get a say.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from ..deps import merchant_api_factory
from ..ids import hash_ip
from .. import plans
from ..security import api_merchant, db_dep
from ..serializers import affiliate_obj, commission_obj, payout_obj, referral_obj, reward_obj
from ..services import rewards
from ..services.affiliates import AffiliateError, add_by_email
from ..services.payouts import create_payout, payable
from ..services.referrals import AttachInput, attach_referral, find_referral
from . import merchant as merchant_routes
from .merchant import AffiliatePatch, DomainIn, RuleIn, campaign_out, domain_out, patch_affiliate, rule_doc

router = APIRouter(prefix="/v1", tags=["server-api"])


class ReferralIn(BaseModel):
    referral: str | None = Field(default=None, description="kr_ref cookie / Kickrail.referral value")
    via: str | None = Field(default=None, description="the ?via= token, if you captured it yourself")
    code: str | None = Field(default=None, description="creator code typed into a 'who referred you?' field")
    email: EmailStr | None = None
    user_id: str | None = Field(default=None, max_length=200, description="your own user id")
    stripe_customer_id: str | None = Field(default=None, pattern=r"^cus_[A-Za-z0-9]+$")
    ip: str | None = Field(default=None, max_length=64, description="the signup request's IP, for self-referral checks")


referral_out = referral_obj


async def managed_api(m=Depends(api_merchant)) -> dict:
    """Reporting signups (POST /referrals, lookup) works on every plan; managing
    affiliates, commissions and payouts over the API is on Growth and up."""
    plans.require(m, "api")
    return m


@router.post("/referrals")
async def create_referral(body: ReferralIn, m=Depends(api_merchant), db=Depends(db_dep)):
    if not (body.email or body.user_id or body.stripe_customer_id):
        raise HTTPException(422, "send at least one of email, user_id, stripe_customer_id")
    hit = await attach_referral(
        db,
        m,
        AttachInput(
            click_id=body.referral if body.referral and body.referral.startswith("kr_") else None,
            token=body.via,
            code=body.code,
            email=body.email,
            external_user_id=body.user_id,
            stripe_customer_id=body.stripe_customer_id,
            ip_hash=hash_ip(body.ip) if body.ip else None,
        ),
    )
    if not hit:
        return {"referred": False}
    referral, created = hit
    return {"referred": True, "created": created, "referral": referral_out(referral)}


@router.get("/referrals/lookup")
async def lookup(email: str | None = None, user_id: str | None = None, stripe_customer_id: str | None = None, m=Depends(api_merchant), db=Depends(db_dep)):
    r = await find_referral(db, m["_id"], email, user_id, stripe_customer_id)
    return {"referred": bool(r), "referral": referral_out(r) if r else None}


# ---------- read and manage the program ----------

Limit = Query(default=25, ge=1, le=100)


async def page(coll, q: dict, limit: int, starting_after: str | None, shape) -> dict:
    """Newest first. Pass the last id you got as starting_after for the next page."""
    if starting_after:
        anchor = await coll.find_one({**q, "_id": starting_after}, {"created_at": 1})
        if not anchor:
            raise HTTPException(400, "starting_after is not an object in this list")
        q = {**q, "$or": [{"created_at": {"$lt": anchor["created_at"]}}, {"created_at": anchor["created_at"], "_id": {"$lt": starting_after}}]}
    rows = await coll.find(q).sort([("created_at", -1), ("_id", -1)]).limit(limit + 1).to_list(None)
    data = [await shape(r) for r in rows[:limit]]
    return {"object": "list", "data": data, "has_more": len(rows) > limit}


async def _affiliate_shape(db, m: dict):
    async def shape(a: dict) -> dict:
        user = await db.users.find_one({"_id": a["user_id"]})
        links = await db.affiliate_links.find({"affiliate_id": a["_id"]}).sort("created_at", 1).to_list(None)
        codes = await db.affiliate_codes.find({"affiliate_id": a["_id"]}).sort("created_at", 1).to_list(None)
        campaign = await db.campaigns.find_one({"_id": a["campaign_id"]})
        return affiliate_obj(m, a, user, links, codes, campaign)

    return shape


async def _plain(shape):
    async def f(doc):
        return shape(doc)

    return f


@router.get("/affiliates")
async def list_affiliates(
    limit: int = Limit, starting_after: str | None = None, status: Literal["pending", "approved", "rejected"] | None = None, email: str | None = None, campaign_id: str | None = None,
    m=Depends(managed_api), db=Depends(db_dep),
):
    q: dict = {"merchant_id": m["_id"]} | ({"status": status} if status else {}) | ({"campaign_id": campaign_id} if campaign_id else {})
    if email:
        u = await db.users.find_one({"email": email.strip().lower()}, {"_id": 1})
        q["user_id"] = u["_id"] if u else "-"
    return await page(db.affiliates, q, limit, starting_after, await _affiliate_shape(db, m))


async def _api_aff(db, m: dict, affiliate_id: str) -> dict:
    aff = await db.affiliates.find_one({"_id": affiliate_id, "merchant_id": m["_id"]})
    if not aff:
        raise HTTPException(404, "no such affiliate")
    return aff


@router.get("/affiliates/{affiliate_id}")
async def get_affiliate(affiliate_id: str, m=Depends(managed_api), db=Depends(db_dep)):
    return await (await _affiliate_shape(db, m))(await _api_aff(db, m, affiliate_id))


class AffiliateCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    campaign_id: str | None = None
    status: Literal["pending", "approved"] = "approved"
    token: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{3,32}$", description="the ?via= value; generated from the name if omitted")
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{3,20}$")
    rate_override: RuleIn | None = None
    metadata: dict[str, str] | None = Field(default=None, max_length=20)
    send_welcome_email: bool = True


@router.post("/affiliates")
async def create(body: AffiliateCreate, m=Depends(managed_api), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    """Add an affiliate from your own app. People without a Kickrail account get one
    without a password, and the welcome email carries a link to set it."""
    try:
        aff, created = await add_by_email(
            db, m, body.email, body.name, factory, status=body.status, campaign_id=body.campaign_id, token=body.token, code=body.code,
            rate_override=rule_doc(body.rate_override) if body.rate_override else None, metadata=body.metadata, send_welcome=body.send_welcome_email,
        )
    except AffiliateError as e:
        raise HTTPException(e.status, str(e))
    return {**await (await _affiliate_shape(db, m))(aff), "created": created}


@router.patch("/affiliates/{affiliate_id}")
async def update(affiliate_id: str, body: AffiliatePatch, m=Depends(managed_api), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    res = await patch_affiliate(db, m, await _api_aff(db, m, affiliate_id), body, factory)
    return {**await (await _affiliate_shape(db, m))(await _api_aff(db, m, affiliate_id)), "warning": res.get("warning")}


@router.get("/referrals")
async def list_referrals(limit: int = Limit, starting_after: str | None = None, affiliate_id: str | None = None, status: Literal["lead", "customer"] | None = None, m=Depends(managed_api), db=Depends(db_dep)):
    q = {"merchant_id": m["_id"]} | ({"affiliate_id": affiliate_id} if affiliate_id else {}) | ({"status": status} if status else {})
    return await page(db.referrals, q, limit, starting_after, await _plain(referral_obj))


@router.get("/referrals/{referral_id}")
async def get_referral(referral_id: str, m=Depends(managed_api), db=Depends(db_dep)):
    r = await db.referrals.find_one({"_id": referral_id, "merchant_id": m["_id"]})
    if not r:
        raise HTTPException(404, "no such referral")
    return referral_obj(r)


@router.get("/commissions")
async def list_commissions(
    limit: int = Limit, starting_after: str | None = None, affiliate_id: str | None = None, referral_id: str | None = None,
    status: Literal["pending", "paid", "void"] | None = None, m=Depends(managed_api), db=Depends(db_dep),
):
    q = {"merchant_id": m["_id"]} | ({"affiliate_id": affiliate_id} if affiliate_id else {}) | ({"referral_id": referral_id} if referral_id else {}) | ({"status": status} if status else {})
    return await page(db.commissions, q, limit, starting_after, await _plain(commission_obj))


@router.get("/commissions/{commission_id}")
async def get_commission(commission_id: str, m=Depends(managed_api), db=Depends(db_dep)):
    c = await db.commissions.find_one({"_id": commission_id, "merchant_id": m["_id"]})
    if not c:
        raise HTTPException(404, "no such commission")
    return commission_obj(c)


async def _reward_out(db, r: dict) -> dict:
    return reward_obj(r, await db.referrals.find_one({"_id": r["referral_id"]}))


@router.get("/rewards")
async def list_rewards(
    limit: int = Limit, starting_after: str | None = None, affiliate_id: str | None = None, referral_id: str | None = None,
    status: Literal["earned", "fulfilled", "void"] | None = None, recipient: Literal["affiliate", "customer"] | None = None,
    m=Depends(managed_api), db=Depends(db_dep),
):
    """Rewards from campaigns whose reward isn't cash. Held ones (a possible self-referral) are
    listed but can't be fulfilled until you approve the referral."""
    q = {"merchant_id": m["_id"]} | {k: v for k, v in {"affiliate_id": affiliate_id, "referral_id": referral_id, "status": status, "recipient": recipient}.items() if v}

    async def shape(r):
        return await _reward_out(db, r)

    return await page(db.rewards, q, limit, starting_after, shape)


@router.get("/rewards/{reward_id}")
async def get_reward(reward_id: str, m=Depends(managed_api), db=Depends(db_dep)):
    r = await db.rewards.find_one({"_id": reward_id, "merchant_id": m["_id"]})
    if not r:
        raise HTTPException(404, "no such reward")
    return await _reward_out(db, r)


class FulfillIn(BaseModel):
    note: str | None = Field(default=None, max_length=300, description="what you gave, e.g. a coupon id")


@router.post("/rewards/{reward_id}/fulfill")
async def fulfill_reward(reward_id: str, body: FulfillIn | None = None, m=Depends(managed_api), db=Depends(db_dep)):
    """Record that you handed the reward out. Safe to repeat."""
    try:
        r = await rewards.fulfill(db, m["_id"], reward_id, body.note if body else None, by="api")
    except rewards.RewardError as e:
        raise HTTPException(e.status, str(e))
    return await _reward_out(db, r)


@router.get("/domains")
async def list_domains(m=Depends(managed_api)):
    """Custom portal domains. A domain is live once its CNAME is verified and HTTPS works."""
    return {"data": [domain_out(d) for d in m.get("portal_domains") or []]}


@router.post("/domains")
async def add_domain(body: DomainIn, m=Depends(managed_api), db=Depends(db_dep)):
    return domain_out((await merchant_routes.add_domain(body, m=m, db=db))["domain"])


@router.post("/domains/{host}/verify")
async def verify_domain(host: str, m=Depends(managed_api), db=Depends(db_dep)):
    return domain_out((await merchant_routes.verify_domain(host, m=m, db=db))["domain"])


@router.post("/domains/{host}/primary")
async def make_primary(host: str, m=Depends(managed_api), db=Depends(db_dep)):
    out = await merchant_routes.make_primary(host, m=m, db=db)
    return {"data": [domain_out(d) for d in out["portal_domains"]]}


@router.delete("/domains/{host}")
async def remove_domain(host: str, m=Depends(managed_api), db=Depends(db_dep)):
    await merchant_routes.remove_domain(host, m=m, db=db)
    return {"deleted": True, "host": host.lower()}


@router.get("/payouts")
async def list_payouts(limit: int = Limit, starting_after: str | None = None, m=Depends(managed_api), db=Depends(db_dep)):
    return await page(db.payouts, {"merchant_id": m["_id"]}, limit, starting_after, await _plain(payout_obj))


@router.get("/payouts/{payout_id}")
async def get_payout(payout_id: str, m=Depends(managed_api), db=Depends(db_dep)):
    p = await db.payouts.find_one({"_id": payout_id, "merchant_id": m["_id"]})
    if not p:
        raise HTTPException(404, "no such payout")
    return payout_obj(p)


class PayoutCreate(BaseModel):
    affiliate_ids: list[str] = Field(min_length=1, max_length=100)
    currency: str | None = Field(default=None, pattern=r"^[a-z]{3}$", description="needed only when those affiliates have balances in more than one currency")
    reference: str = Field(default="", max_length=200, description="what you paid with, e.g. a coupon or transfer id")


@router.post("/payouts")
async def record_payout(body: PayoutCreate, m=Depends(managed_api), db=Depends(db_dep)):
    """Record that you paid these affiliates' payable balances yourself, in cash or in
    kind. Same as a manual payout in the dashboard: commissions become paid and
    payout.paid goes out."""
    currencies = {l["currency"] for l in await payable(db, m["_id"]) if l["affiliate_id"] in set(body.affiliate_ids)}
    currency = body.currency or (currencies.pop() if len(currencies) == 1 else None)
    if not currency:
        raise HTTPException(409, "nothing payable for these affiliates" if not currencies else "these balances are in more than one currency; pass currency")
    try:
        p = await create_payout(db, m, currency, "manual", None, affiliate_ids=body.affiliate_ids, reference=body.reference)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return payout_obj(p)


@router.get("/campaigns")
async def list_campaigns(m=Depends(managed_api), db=Depends(db_dep)):
    rows = await db.campaigns.find({"merchant_id": m["_id"]}).sort("created_at", 1).to_list(None)
    return {"object": "list", "data": [{**campaign_out(c, m), "object": "campaign"} for c in rows], "has_more": False}
