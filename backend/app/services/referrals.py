"""Attribution: tie a person (email / app user id / Stripe customer) to an affiliate.

Signals, strongest first: the click id from the tracking cookie, the ?via= token,
a Stripe promotion code redeemed at checkout, a creator code typed at signup.
By default the first referral wins: once a person is attributed, another affiliate's
later click does not take them. A program can switch to last touch, where a newer
click, link or code moves a person to that affiliate until their first payment.

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

from ..db import run_in_transaction
from ..domain.fraud import canonical_email, self_referral_flags
from ..ids import new_id
from . import audit, notify, rewards

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


async def _promotion_code_name(db: AsyncDatabase, aff: dict, promotion_code_id: str) -> str | None:
    """The code a customer typed at checkout, from the Stripe promotion code it maps to."""
    match = {"$or": [{"stripe_promotion_code_id": promotion_code_id}, {"stripe_retired_promotion_code_ids": promotion_code_id}]}
    if await db.affiliates.find_one({"_id": aff["_id"], **match}, {"_id": 1}):
        return aff.get("code")
    row = await db.affiliate_codes.find_one({"affiliate_id": aff["_id"], **match}, {"code": 1})
    return row and row["code"]


async def resolve_affiliate(db: AsyncDatabase, merchant_id: str, inp: AttachInput) -> tuple[dict, str, str | None, dict | None] | None:
    """(affiliate, source, click id, via). `via` names the link token or creator code that
    brought the person in, since an affiliate can have several of each."""
    approved = {"merchant_id": merchant_id, "status": "approved"}
    if inp.click_id:
        click = await db.clicks.find_one({"_id": inp.click_id, "merchant_id": merchant_id})
        if click:
            aff = await db.affiliates.find_one({**approved, "_id": click["affiliate_id"]})
            if aff:
                return aff, "link", click["_id"], {"token": click["token"]} if click.get("token") else None
    if inp.token:
        aff = await affiliate_by_token(db, merchant_id, inp.token)
        if aff:
            return aff, "link", None, {"token": inp.token.strip().lower()}
    if inp.promotion_code_id:
        aff = await _by_field(db, merchant_id, "stripe_promotion_code_id", inp.promotion_code_id, db.affiliate_codes, True) or await _by_field(
            db, merchant_id, "stripe_retired_promotion_code_ids", inp.promotion_code_id, db.affiliate_codes, True
        )
        if aff:
            code = await _promotion_code_name(db, aff, inp.promotion_code_id)
            return aff, "code", None, {"code": code} if code else None
    if inp.code:
        aff = await affiliate_by_code(db, merchant_id, inp.code)
        if aff:
            return aff, "code", None, {"code": inp.code.strip().upper()}
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


def _auto_reject(merchant: dict, flags: list) -> dict:
    """The program chose to reject suspected self-referrals outright instead of holding them for review."""
    if flags and (merchant.get("settings") or {}).get("reject_self_referrals"):
        return {"rejected": True, "flags_cleared": True, "auto_rejected": True}
    return {}


async def _is_team_email(db: AsyncDatabase, merchant: dict, email: str) -> bool:
    ids = list({merchant.get("owner_id"), *(merchant.get("member_ids") or [])} - {None})
    target = canonical_email(email)
    async for u in db.users.find({"_id": {"$in": ids}}, {"email": 1}):
        if u.get("email") and canonical_email(u["email"]) == target:
            return True
    return False


async def _last_touch(db: AsyncDatabase, merchant: dict, existing: dict, inp: AttachInput, email: str | None) -> dict:
    """Under last-touch attribution, the fields that move an unpaid referral to the
    affiliate behind a newer click, link or code. Empty when it stays put."""
    if (merchant.get("settings") or {}).get("attribution") != "last":
        return {}
    if existing.get("first_paid_at") or existing.get("rejected") or not (inp.click_id or inp.token or inp.code or inp.promotion_code_id):
        return {}
    hit = await resolve_affiliate(db, merchant["_id"], inp)
    if not hit or hit[0]["_id"] == existing["affiliate_id"]:
        return {}
    affiliate, source, click_id, via = hit
    click = await db.clicks.find_one({"_id": click_id}, {"test": 1}) if click_id else None
    # A test click never takes a real referral.
    if click and click.get("test") and not existing.get("test"):
        return {}
    aff_user = await db.users.find_one({"_id": affiliate["user_id"]})
    who = email or existing.get("email")
    flags = self_referral_flags(aff_user["email"], aff_user.get("ip_hashes", []), who, inp.ip_hash) if aff_user else []
    return {
        "affiliate_id": affiliate["_id"],
        "campaign_id": affiliate["campaign_id"],
        "click_id": click_id,
        "source": source,
        "via": via,
        "flags": flags,
        "flags_cleared": False,
        **_auto_reject(merchant, flags),
        "test": bool(click and click.get("test")),
        "moved_at": datetime.now(UTC),
    }


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
        fill = await _last_touch(db, merchant, existing, inp, email)
        if email and not existing.get("email"):
            fill["email"] = email
        if inp.external_user_id and not existing.get("external_user_id"):
            fill["external_user_id"] = inp.external_user_id
        if inp.stripe_customer_id and not existing.get("stripe_customer_id"):
            fill["stripe_customer_id"] = inp.stripe_customer_id
        if not fill:
            return existing, False
        moved = "affiliate_id" in fill
        if (moved and existing.get("stripe_customer_id")) or "stripe_customer_id" in fill:
            fill["stripe_sync_due"] = True
        updated = {**existing, **fill}
        update: dict = {"$set": fill}
        if moved:
            update["$push"] = {"previous_affiliates": {"affiliate_id": existing["affiliate_id"], "click_id": existing.get("click_id"), "until": fill["moved_at"]}}
            if not fill.get("test"):
                update["$unset"] = {"test": ""}
                updated.pop("test", None)
            fill.pop("test", None)

        async def save(tdb):
            await tdb.referrals.update_one({"_id": existing["_id"]}, update)
            if moved:
                await notify.referral_updated(tdb, merchant["_id"], updated, existing["affiliate_id"])
                if fill.get("flags"):
                    await notify.self_referral(tdb, merchant, updated)

        try:
            await run_in_transaction(db, save)
        except DuplicateKeyError:
            # Another referral already holds one of these ids; keep both as they are.
            return existing, False
        return updated, False

    hit = await resolve_affiliate(db, merchant["_id"], inp)
    if not hit:
        return None
    affiliate, source, click_id, via = hit
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
        "via": via,
        "status": "lead",
        "email": email,
        "external_user_id": inp.external_user_id,
        "stripe_customer_id": inp.stripe_customer_id,
        "first_paid_at": None,
        "flags": flags,
        **_auto_reject(merchant, flags),
        "auto": inp.auto or None,
        # Came through a kr_test=1 link: shown to the merchant, left out of counts and commissions.
        "test": True if click and click.get("test") else None,
        "stripe_sync_due": True if inp.stripe_customer_id else None,
        "created_at": datetime.now(UTC),
    }
    # Sparse indexes skip missing fields, not nulls, so drop the empty ones.
    referral = {k: v for k, v in referral.items() if v is not None or k in ("first_paid_at",)}
    async def create(tdb):
        await tdb.referrals.insert_one(referral)
        await notify.referral_created(tdb, merchant["_id"], referral)
        if flags:
            await notify.self_referral(tdb, merchant, referral)
        if referral.get("auto_rejected"):
            await audit.record(tdb, merchant["_id"], "referral.rejected", referral["_id"], automatic=True, reason="suspected self-referral")

    try:
        await run_in_transaction(db, create)
    except DuplicateKeyError:
        # A concurrent request (say the browser script and the merchant's server) won the race.
        if not _retry:
            raise
        return await attach_referral(db, merchant, inp, customer_created, _retry=False)
    # A form the script picked up on its own may be a newsletter box, not a signup.
    if not inp.auto and not referral.get("test") and not referral.get("rejected"):
        await award_lead_bounty(db, merchant, referral)
        await rewards.on_signup(db, merchant, referral)
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
    async def create(tdb):
        await tdb.commissions.insert_one(doc)
        await notify.commission_created(tdb, merchant, doc)

    try:
        await run_in_transaction(db, create)
    except DuplicateKeyError:
        return None
    return doc
