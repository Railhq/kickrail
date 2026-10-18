"""Attribution: tie a person (email / app user id / Stripe customer) to an affiliate.

Signals, strongest first: the click id from the tracking cookie, the ?via= token,
a Stripe promotion code redeemed at checkout, a creator code typed at signup.
First referral wins: once a person is attributed, another affiliate's later click
does not take them.

An affiliate can have extra links (affiliate_links, each its own token and landing
page) and extra codes (affiliate_codes); they resolve exactly like the main ones.

Leads the script captured on its own from a form ("auto") are weaker evidence: the
person may already have been a customer who clicked a link and then logged in. Such a
lead only takes a Stripe customer created after it.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from ..domain.fraud import canonical_email, self_referral_flags
from ..ids import new_id
from . import notify

log = logging.getLogger(__name__)


@dataclass
class AttachInput:
    click_id: str | None = None
    token: str | None = None
    code: str | None = None
    promotion_code_id: str | None = None
    email: str | None = None
    external_user_id: str | None = None
    stripe_customer_id: str | None = None
    ip_hash: str | None = None
    auto: bool = False

# Clock and ordering slack: a checkout can create the customer just before the form's request lands.
AUTO_LEAD_SLACK = timedelta(minutes=10)


async def _by_field(db: AsyncDatabase, merchant_id: str, field: str, value: str, extra, approved_only: bool) -> dict | None:
    q = {"merchant_id": merchant_id} | ({"status": "approved"} if approved_only else {})
    aff = await db.affiliates.find_one({**q, field: value})
    if aff:
        return aff
    row = await extra.find_one({"merchant_id": merchant_id, field: value})
    return await db.affiliates.find_one({**q, "_id": row["affiliate_id"]}) if row else None


async def affiliate_by_token(db: AsyncDatabase, merchant_id: str, token: str, approved_only: bool = True) -> dict | None:
    return await _by_field(db, merchant_id, "token", token.strip().lower(), db.affiliate_links, approved_only)


async def affiliate_by_code(db: AsyncDatabase, merchant_id: str, code: str) -> dict | None:
    return await _by_field(db, merchant_id, "code", code.strip().upper(), db.affiliate_codes, True)


async def token_taken(db: AsyncDatabase, merchant_id: str, token: str) -> bool:
    return bool(await db.affiliates.find_one({"merchant_id": merchant_id, "token": token}) or await db.affiliate_links.find_one({"merchant_id": merchant_id, "token": token}))


async def code_taken(db: AsyncDatabase, merchant_id: str, code: str) -> bool:
    return bool(await db.affiliates.find_one({"merchant_id": merchant_id, "code": code}) or await db.affiliate_codes.find_one({"merchant_id": merchant_id, "code": code}))


async def resolve_affiliate(db: AsyncDatabase, merchant_id: str, inp: AttachInput) -> tuple[dict, str, str | None] | None:
    approved = {"merchant_id": merchant_id, "status": "approved"}
    if inp.click_id:
        click = await db.clicks.find_one({"_id": inp.click_id, "merchant_id": merchant_id})
        if click:
            aff = await db.affiliates.find_one({**approved, "_id": click["affiliate_id"]})
            if aff:
                return aff, "link", click["_id"]
    if inp.token:
        aff = await affiliate_by_token(db, merchant_id, inp.token)
        if aff:
            return aff, "link", None
    if inp.promotion_code_id:
        aff = await _by_field(db, merchant_id, "stripe_promotion_code_id", inp.promotion_code_id, db.affiliate_codes, True)
        if aff:
            return aff, "code", None
    if inp.code:
        aff = await affiliate_by_code(db, merchant_id, inp.code)
        if aff:
            return aff, "code", None
    return None


async def find_referral(db: AsyncDatabase, merchant_id: str, email: str | None = None, external_user_id: str | None = None, stripe_customer_id: str | None = None) -> dict | None:
    ors = []
    if stripe_customer_id:
        ors.append({"stripe_customer_id": stripe_customer_id})
    if external_user_id:
        ors.append({"external_user_id": external_user_id})
    if email:
        ors.append({"email": email.strip().lower()})
    if not ors:
        return None
    return await db.referrals.find_one({"merchant_id": merchant_id, "$or": ors}, sort=[("created_at", 1)])


async def _older_customer(db: AsyncDatabase, referral: dict, customer_id: str, customer_created) -> bool:
    """True when an auto-captured lead is being matched to a Stripe customer that
    existed before the lead; remembered so later invoices skip the lookup."""
    if customer_id in referral.get("rejected_customers", []):
        return True
    try:
        created = await customer_created(customer_id)
    except Exception:  # missing permission or network: keep attributing
        log.warning("customer lookup failed for %s", customer_id, exc_info=True)
        return False
    lead_at = referral["created_at"].replace(tzinfo=referral["created_at"].tzinfo or UTC)
    if not created or created >= lead_at - AUTO_LEAD_SLACK:
        return False
    await db.referrals.update_one({"_id": referral["_id"]}, {"$addToSet": {"rejected_customers": customer_id, "flags": {"kind": "existing_customer", "detail": f"Stripe customer {customer_id} existed before this signup was captured"}}})
    return True


async def _is_team_email(db: AsyncDatabase, merchant: dict, email: str) -> bool:
    ids = list({merchant.get("owner_id"), *(merchant.get("member_ids") or [])} - {None})
    target = canonical_email(email)
    async for u in db.users.find({"_id": {"$in": ids}}, {"email": 1}):
        if u.get("email") and canonical_email(u["email"]) == target:
            return True
    return False


async def attach_referral(db: AsyncDatabase, merchant: dict, inp: AttachInput, customer_created=None, _retry: bool = True) -> tuple[dict, bool] | None:
    """Returns (referral, created) or None when nothing points at an approved affiliate.
    `customer_created(customer_id)` gives a Stripe customer's creation time, for the
    auto-lead check."""
    email = inp.email.strip().lower() if inp.email else None
    existing = await find_referral(db, merchant["_id"], email, inp.external_user_id, inp.stripe_customer_id)
    if existing:
        weak = existing.get("auto") and not existing.get("stripe_customer_id") and not (inp.click_id or inp.token)
        if weak and inp.stripe_customer_id and customer_created and await _older_customer(db, existing, inp.stripe_customer_id, customer_created):
            return None
        fill = {}
        if email and not existing.get("email"):
            fill["email"] = email
        if inp.external_user_id and not existing.get("external_user_id"):
            fill["external_user_id"] = inp.external_user_id
        if inp.stripe_customer_id and not existing.get("stripe_customer_id"):
            fill["stripe_customer_id"] = inp.stripe_customer_id
        if fill:
            try:
                await db.referrals.update_one({"_id": existing["_id"]}, {"$set": fill})
            except DuplicateKeyError:
                # Another referral already holds one of these ids; keep both as they are.
                return existing, False
        return {**existing, **fill}, False

    hit = await resolve_affiliate(db, merchant["_id"], inp)
    if not hit:
        return None
    affiliate, source, click_id = hit
    # The program's own team signing up to their own product is never a referral.
    if email and await _is_team_email(db, merchant, email):
        return None
    click = await db.clicks.find_one({"_id": click_id}, {"test": 1}) if click_id else None
    aff_user = await db.users.find_one({"_id": affiliate["user_id"]})
    flags = self_referral_flags(aff_user["email"], aff_user.get("ip_hashes", []), email, inp.ip_hash) if aff_user else []
    referral = {
        "_id": new_id("ref"),
        "merchant_id": merchant["_id"],
        "affiliate_id": affiliate["_id"],
        "campaign_id": affiliate["campaign_id"],
        "click_id": click_id,
        "source": source,
        "status": "lead",
        "email": email,
        "external_user_id": inp.external_user_id,
        "stripe_customer_id": inp.stripe_customer_id,
        "first_paid_at": None,
        "flags": flags,
        "auto": inp.auto or None,
        # Came through a kr_test=1 link: shown to the merchant, left out of counts and commissions.
        "test": True if click and click.get("test") else None,
        "created_at": datetime.now(UTC),
    }
    # Sparse indexes skip missing fields, not nulls, so drop the empty ones.
    referral = {k: v for k, v in referral.items() if v is not None or k in ("first_paid_at",)}
    try:
        await db.referrals.insert_one(referral)
    except DuplicateKeyError:
        # A concurrent request (say the browser script and the merchant's server) won the race.
        if not _retry:
            raise
        return await attach_referral(db, merchant, inp, customer_created, _retry=False)
    await notify.referral_created(db, merchant["_id"], referral)
    # A form the script picked up on its own may be a newsletter box, not a signup.
    if not inp.auto and not referral.get("test"):
        await award_lead_bounty(db, merchant, referral)
    return referral, True


async def award_lead_bounty(db: AsyncDatabase, merchant: dict, referral: dict) -> dict | None:
    """A fixed amount for the signup itself, before anyone pays. One per referral."""
    campaign = await db.campaigns.find_one({"_id": referral["campaign_id"]})
    bounty = (campaign or {}).get("lead_bounty")
    if not bounty or bounty.get("cents", 0) <= 0:
        return None
    now = datetime.now(UTC)
    doc = {
        "_id": new_id("com"),
        "merchant_id": merchant["_id"],
        "affiliate_id": referral["affiliate_id"],
        "referral_id": referral["_id"],
        "campaign_id": campaign["_id"],
        "kind": "lead",
        "source_key": f"lead:{referral['_id']}",
        "base_cents": 0,
        "original_amount_cents": bounty["cents"],
        "amount_cents": bounty["cents"],
        "refunded_cents": 0,
        "currency": bounty["currency"],
        "status": "pending",
        "held": bool(referral.get("flags")),
        "due_at": now + timedelta(days=campaign["hold_days"]),
        "created_at": now,
    }
    try:
        await db.commissions.insert_one(doc)
    except DuplicateKeyError:
        return None
    await notify.commission_created(db, merchant, doc)
    return doc
