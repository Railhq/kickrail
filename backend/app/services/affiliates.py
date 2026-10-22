"""Creating affiliates and their links and codes. Shared by the join page, the
merchant dashboard and the /v1 API, so all three follow the same rules."""

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from .. import plans
from ..db import run_in_transaction
from ..domain.commission import describe_rule
from ..ids import new_id, random_id, sha256, slugify
from ..security import can_be_paid
from ..serializers import affiliate_url, code_obj, link_obj, portal_base
from . import fx, notify
from .referrals import code_taken, token_taken

TOKEN = re.compile(r"^[a-z0-9_-]{3,32}$")
CODE = re.compile(r"^[A-Z0-9]{3,20}$")


class AffiliateError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def program_public(m: dict, campaign: dict | None) -> dict:
    b = m.get("branding") or {}
    return {
        "slug": m["slug"],
        "campaign": campaign["slug"] if campaign and not campaign.get("is_default") and campaign.get("slug") else None,
        "name": m["name"],
        "website": m["website"],
        "terms": describe_rule(campaign) if campaign else None,
        "hold_days": campaign["hold_days"] if campaign else None,
        "branding": {k: b.get(k) for k in ("logo_url", "color", "headline", "description", "welcome_message", "terms_url")},
        # Free and Starter programs show "Powered by Kickrail" on the join page and portal.
        "powered_by": plans.current(m)["branding"],
    }


async def create_affiliate(
    db: AsyncDatabase, m: dict, user: dict, factory, *, status: str | None = None, campaign_id: str | None = None,
    token: str | None = None, code: str | None = None, rate_override: dict | None = None, metadata: dict | None = None, send_welcome: bool = True, claim_url: str | None = None,
) -> tuple[dict, bool]:
    """Returns (affiliate, created). Joining twice returns the existing one."""
    existing = await db.affiliates.find_one({"merchant_id": m["_id"], "user_id": user["_id"]})
    if existing:
        return existing, False
    campaign = await db.campaigns.find_one({"_id": campaign_id, "merchant_id": m["_id"]} if campaign_id else {"merchant_id": m["_id"], "is_default": True})
    if not campaign:
        raise AffiliateError("campaign not found", 404)
    if token and (not TOKEN.match(token) or await token_taken(db, m["_id"], token)):
        raise AffiliateError("that link name is taken or invalid", 409)
    if code and (not CODE.match(code.upper()) or await code_taken(db, m["_id"], code.upper())):
        raise AffiliateError("that code is taken or invalid", 409)
    base = (slugify(user["name"]).replace("-", "") or "partner")[:16]
    aff = {
        "merchant_id": m["_id"],
        "user_id": user["_id"],
        "campaign_id": campaign["_id"],
        "status": status or ("approved" if m["settings"]["auto_approve"] else "pending"),
        "rate_override": rate_override,
        "metadata": metadata or None,
        "created_at": datetime.now(UTC),
    }
    for attempt in range(8):
        t = token or (base if attempt == 0 else f"{base}{random_id(3).lower()}")
        if len(t) < 3:
            t = f"{t}{random_id(3).lower()}"
        if not token and await db.affiliate_links.find_one({"merchant_id": m["_id"], "token": t}):
            continue
        c = code.upper() if code else t.upper()[:20]
        if not code and await db.affiliate_codes.find_one({"merchant_id": m["_id"], "code": c}):
            c = None
        doc = {**aff, "_id": new_id("aff"), "token": t, "code": c}
        doc = {k: v for k, v in doc.items() if v is not None}
        try:
            await db.affiliates.insert_one(doc)
        except DuplicateKeyError as e:
            if token or code:
                raise AffiliateError("that link name or code is taken", 409) from e
            continue
        await sync_promotion_code(db, m, doc, factory)
        doc = await db.affiliates.find_one({"_id": doc["_id"]})
        await notify.affiliate_created(db, m, doc, send_welcome=send_welcome, claim_url=claim_url)
        return doc, True
    raise AffiliateError("could not create a unique link, try again", 409)


async def add_by_email(db: AsyncDatabase, m: dict, email: str, name: str, factory, **kw) -> tuple[dict, bool]:
    """The merchant adds someone (dashboard or API). People without a Kickrail account
    get one with no password; the welcome email carries a one-time link to set it."""
    email = email.strip().lower()
    user = await db.users.find_one({"email": email})
    claim_url = None
    if not user or (not user.get("password_hash") and user.get("created_via") == m["_id"]):
        token = random_id(32)
        claim_url = f"{portal_base(m)}/claim?token={token}"
        if user:
            await db.users.update_one({"_id": user["_id"]}, {"$set": {"claim_token_hash": sha256(token)}})
        else:
            user = {"_id": new_id("usr"), "email": email, "name": name.strip(), "ip_hashes": [], "claim_token_hash": sha256(token), "created_via": m["_id"], "created_at": datetime.now(UTC)}
            try:
                await db.users.insert_one(user)
            except DuplicateKeyError:
                user, claim_url = await db.users.find_one({"email": email}), None
    return await create_affiliate(db, m, user, factory, claim_url=claim_url, **kw)


async def _promotion_code(db, merchant: dict, aff: dict, code: str, factory) -> tuple[str | None, str | None]:
    """(promotion code id, warning). Codes become real Stripe promotion codes when the
    campaign has a coupon, so a code heard on a podcast works at checkout."""
    if aff["status"] != "approved" or not merchant.get("stripe"):
        return None, None
    campaign = await db.campaigns.find_one({"_id": aff["campaign_id"]})
    if not campaign or not campaign.get("stripe_coupon_id"):
        return None, None
    try:
        return await factory(merchant).create_promotion_code(campaign["stripe_coupon_id"], code, aff["_id"]), None
    except Exception as e:
        return None, f"code saved, but Stripe did not create the promotion code: {getattr(e, 'user_message', None) or e}"


async def sync_promotion_code(db, merchant: dict, aff: dict, factory) -> str | None:
    """Make sure the main code and every extra code are redeemable. Returns a warning."""
    warning = None
    if aff.get("code") and not (aff.get("stripe_promotion_code_id") and aff.get("stripe_promotion_code") == aff["code"]):
        pc_id, warning = await _promotion_code(db, merchant, aff, aff["code"], factory)
        if pc_id:
            await db.affiliates.update_one({"_id": aff["_id"]}, {"$set": {"stripe_promotion_code_id": pc_id, "stripe_promotion_code": aff["code"]}})
    async for extra in db.affiliate_codes.find({"affiliate_id": aff["_id"], "stripe_promotion_code_id": {"$exists": False}}):
        pc_id, w = await _promotion_code(db, merchant, aff, extra["code"], factory)
        warning = warning or w
        if pc_id:
            await db.affiliate_codes.update_one({"_id": extra["_id"]}, {"$set": {"stripe_promotion_code_id": pc_id}})
    return warning


async def _retire_promotion_codes(db, merchant: dict, aff: dict, factory) -> str | None:
    """Switch off the affiliate's promotion codes so new ones can take the same code on
    another coupon (Stripe allows one active code per string). The old ids stay
    searchable, so a checkout started with an old code is still credited."""
    docs = [(db.affiliates, aff)] + [(db.affiliate_codes, c) async for c in db.affiliate_codes.find({"affiliate_id": aff["_id"], "stripe_promotion_code_id": {"$exists": True}})]
    for coll, doc in docs:
        pc_id = doc.get("stripe_promotion_code_id")
        if not pc_id:
            continue
        try:
            await factory(merchant).deactivate_promotion_code(pc_id)
        except Exception as e:
            return f"Stripe did not switch off promotion code {doc.get('code')}: {getattr(e, 'user_message', None) or e}"
        await coll.update_one({"_id": doc["_id"]}, {"$addToSet": {"stripe_retired_promotion_code_ids": pc_id}, "$unset": {"stripe_promotion_code_id": "", "stripe_promotion_code": ""}})
    return None


async def sync_campaign_codes(db, merchant: dict, campaign_id: str, factory, replace: bool = False) -> str | None:
    """After a campaign's coupon changes, put its affiliates' codes on the new coupon.
    With `replace`, codes on the old coupon are switched off first; otherwise codes
    already tied to a promotion code keep it. Returns a warning."""
    warning = None
    async for aff in db.affiliates.find({"merchant_id": merchant["_id"], "campaign_id": campaign_id}):
        if replace and merchant.get("stripe"):
            w = await _retire_promotion_codes(db, merchant, aff, factory)
            if w:
                warning = warning or w
                continue
            aff = await db.affiliates.find_one({"_id": aff["_id"]})
        if aff["status"] == "approved":
            warning = warning or await sync_promotion_code(db, merchant, aff, factory)
    return warning


def check_landing(m: dict, landing_url: str | None) -> str | None:
    if not landing_url:
        return None
    parts = urlsplit(landing_url.strip())
    site = (urlsplit(m["website"]).hostname or "").removeprefix("www.")
    host = (parts.hostname or "").removeprefix("www.")
    if parts.scheme not in ("http", "https") or not host or not (host == site or host.endswith(f".{site}")):
        raise AffiliateError(f"landing pages must be on {site}", 422)
    return landing_url.strip()


async def add_link(db: AsyncDatabase, m: dict, aff: dict, token: str, landing_url: str | None = None, label: str = "") -> dict:
    token = token.strip().lower()
    if not TOKEN.match(token):
        raise AffiliateError("link names are 3-32 lowercase letters, digits, - or _", 422)
    if await token_taken(db, m["_id"], token):
        raise AffiliateError("that link name is taken in this program", 409)
    if await db.affiliate_links.count_documents({"affiliate_id": aff["_id"]}) >= 50:
        raise AffiliateError("an affiliate can have at most 50 links", 422)
    link = {"_id": new_id("lnk"), "merchant_id": m["_id"], "affiliate_id": aff["_id"], "token": token, "landing_url": check_landing(m, landing_url), "label": label.strip()[:80], "created_at": datetime.now(UTC)}
    async def create(tdb):
        await tdb.affiliate_links.insert_one(link)
        await notify.affiliate_updated(tdb, m, aff)

    try:
        await run_in_transaction(db, create)
    except DuplicateKeyError as e:
        raise AffiliateError("that link name is taken in this program", 409) from e
    return link_obj(m, link)


async def add_code(db: AsyncDatabase, m: dict, aff: dict, code: str, factory) -> tuple[dict, str | None]:
    code = code.strip().upper()
    if not CODE.match(code):
        raise AffiliateError("codes are 3-20 letters or digits", 422)
    if await code_taken(db, m["_id"], code):
        raise AffiliateError("another affiliate already uses that code", 409)
    if await db.affiliate_codes.count_documents({"affiliate_id": aff["_id"]}) >= 20:
        raise AffiliateError("an affiliate can have at most 20 extra codes", 422)
    row = {"_id": new_id("cod"), "merchant_id": m["_id"], "affiliate_id": aff["_id"], "code": code, "created_at": datetime.now(UTC)}
    try:
        await db.affiliate_codes.insert_one(row)
    except DuplicateKeyError as e:
        raise AffiliateError("another affiliate already uses that code", 409) from e
    warning = await sync_promotion_code(db, m, aff, factory)
    await notify.affiliate_updated(db, m, aff)
    return code_obj(await db.affiliate_codes.find_one({"_id": row["_id"]})), warning


async def affiliate_view(db: AsyncDatabase, m: dict, aff: dict, user: dict) -> dict:
    """What the affiliate sees for one program. Also what "view as" shows the merchant."""
    campaign = await db.campaigns.find_one({"_id": aff["campaign_id"]})
    last_test = await db.clicks.find_one({"affiliate_id": aff["_id"], "test": True}, sort=[("created_at", -1)])
    links = await db.affiliate_links.find({"affiliate_id": aff["_id"]}).sort("created_at", 1).to_list(None)
    codes = await db.affiliate_codes.find({"affiliate_id": aff["_id"]}).sort("created_at", 1).to_list(None)
    program = program_public(m, campaign)
    if campaign:
        program["terms"] = describe_rule(campaign, aff)
    link = affiliate_url(m, aff["token"], (campaign or {}).get("landing_url"))
    return {
        "affiliate_id": aff["_id"],
        "status": aff["status"],
        "program": program,
        "min_payout_cents": campaign["min_payout_cents"] if campaign else 0,
        "link": link,
        "test_link": f"{link}&kr_test=1",
        "token": aff["token"],
        "code": aff.get("code"),
        "code_redeemable_at_checkout": bool(aff.get("stripe_promotion_code_id")),
        "links": [link_obj(m, l) for l in links],
        "codes": [code_obj(c) for c in codes],
        "can_add_links": m["settings"].get("affiliate_links", True),
        "last_test": {"at": last_test["created_at"], "url": last_test["landing_url"]} if last_test else None,
        "payouts_enabled": bool(user.get("payouts_enabled")),
        "can_be_paid": can_be_paid(user),
        "has_tax_form": bool(user.get("tax_info")),
        "tax_form_required": m["settings"].get("require_tax_form", False),
        "fx": await fx.for_display(db, m["settings"].get("display_currency") or "usd"),
        **await pipeline(db, aff),
    }


async def pipeline(db, aff: dict) -> dict:
    refs = await db.referrals.find({"affiliate_id": aff["_id"], "test": {"$ne": True}}).to_list(None)
    commissions = await db.commissions.find({"affiliate_id": aff["_id"]}).sort("created_at", -1).to_list(None)
    now = datetime.now(UTC)
    totals: dict[str, dict[str, int]] = {}
    for c in commissions:
        if c["status"] == "void":
            continue
        t = totals.setdefault(c["currency"], {"in_hold": 0, "payable": 0, "paid": 0})
        if c["status"] == "paid":
            t["paid"] += c["amount_cents"]
        elif c["due_at"] <= now and not c.get("held"):
            t["payable"] += c["amount_cents"]
        else:
            t["in_hold"] += c["amount_cents"]
    return {
        "clicks": await db.clicks.count_documents({"affiliate_id": aff["_id"], "test": False}),
        "clicks_30d": await db.clicks.count_documents({"affiliate_id": aff["_id"], "test": False, "created_at": {"$gte": now - timedelta(days=30)}}),
        "leads": len(refs),
        "customers": sum(1 for r in refs if r["status"] == "customer"),
        "totals": totals,
        "commissions": [
            {
                "id": c["_id"],
                "kind": "lead" if c.get("kind") == "lead" else "sale",
                "amount_cents": c["amount_cents"],
                "currency": c["currency"],
                "status": c["status"],
                "held_for_review": bool(c.get("held")),
                "clawback": c["amount_cents"] < 0,
                "due_at": c["due_at"],
                "paid_at": c.get("paid_at"),
                "created_at": c["created_at"],
                "void_reason": c.get("void_reason"),
            }
            for c in commissions[:200]
        ],
    }
