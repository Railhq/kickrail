"""Merchant dashboard API (signed-in merchant team members)."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from pymongo.errors import DuplicateKeyError

from .. import plans
from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..db import run_in_transaction
from ..deps import merchant_api_factory, merchant_key_client, paypal_factory, paypal_key_client, merchant_account_client, platform_api, stripe_oauth, stripe_oauth_optional, rewardful_client
from ..domain.commission import describe_rate, describe_rule
from ..ids import new_id, random_id, sha256, slugify
from ..security import MAX_PROGRAMS, can_be_paid, current_merchant, current_user, db_dep
from ..serializers import affiliate_url, code_obj, join_url, link_obj, portal_base
from ..services import audit, fx, notify
from ..services import payouts as payout_svc
from ..services import deletion, rewardful_import, rewards, stripe_sync, terms
from ..services.exports import EXPORTS
from ..services.affiliates import AffiliateError, add_by_email, add_code, add_link, affiliate_view, check_landing, sync_campaign_codes, sync_promotion_code
from ..services.notify import EMAIL_KINDS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/merchant", tags=["merchant"])


def out(doc: dict | None, *drop: str) -> dict | None:
    if doc is None:
        return None
    d = {k: v for k, v in doc.items() if k not in drop}
    d["id"] = d.pop("_id")
    return d


DEFAULT_SETTINGS = {"cookie_days": 60, "param_names": ["via", "ref"], "auto_approve": True, "affiliate_links": True, "require_tax_form": False, "reject_self_referrals": False, "attribution": "first", "display_currency": "usd"}


def plan_summary(m: dict, plan: dict | None = None) -> dict:
    plan = plan or plans.current(m)
    keep = ("id", "name", "status", "comped", "trial_ends_at", "interval", "current_period_end", "cancel_at_period_end", "subscribed", "revenue_cap", "branding")
    usage = m.get("usage") or {}
    return {k: plan.get(k) for k in keep} | {
        "over_limit": bool(usage.get("over_limit")) and not plan["comped"],
        "suggested_plan": usage.get("suggested_plan"),
        "limits": {k: plan[k] for k in ("domains", "campaigns", "teammates", "creator_codes", "api", "stripe_payouts")},
    }


def merchant_out(m: dict) -> dict:
    stripe, paypal = m.get("stripe"), m.get("paypal")
    plan = plans.current(m)
    return {
        "id": m["_id"],
        "name": m["name"],
        "slug": m["slug"],
        "website": m["website"],
        "owner_id": m.get("owner_id"),
        "public_key": m["public_key"],
        "secret_key_hint": m["secret_key_hint"],
        "settings": DEFAULT_SETTINGS | m["settings"] | {"emails": {k: notify.email_on(m, k) for k in EMAIL_KINDS}},
        "branding": m.get("branding") or {},
        "terms": terms.public(m),
        # Oldest first. Past the plan's limit (after a downgrade) they keep working; only adding is blocked.
        "portal_domains": [{**d, "over_limit": i >= plan["domains"]} for i, d in enumerate(sorted(m.get("portal_domains") or [], key=lambda d: d["added_at"]))],
        "domain_limit": plan["domains"],
        "plan": plan_summary(m, plan),
        "portal_url": portal_base(m),
        "join_url": join_url(m),
        "cname_target": get_settings().portal_cname_target,
        "stripe": {"account_id": stripe.get("account_id"), "account_name": stripe.get("account_name"), "livemode": stripe["livemode"], "connected_at": stripe["connected_at"], "mode": "oauth" if stripe.get("oauth") else "key"} if stripe else None,
        "stripe_oauth": get_settings().stripe_oauth,
        "paypal": {"client_id_hint": f"{paypal['client_id'][:6]}…", "mode": paypal["mode"], "connected_at": paypal["connected_at"]} if paypal else None,
        "snippet": snippet(m),
    }


def snippet(m: dict) -> str:
    return f'<script async src="{get_settings().public_url}/api/kr.js?k={m["public_key"]}"></script>'


def new_secret_key() -> tuple[str, str, str]:
    key = f"sk_kr_{random_id(32)}"
    return key, sha256(key), f"sk_kr_…{key[-4:]}"


# ---------- workspace ----------


class MerchantIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    website: HttpUrl


@router.post("")
async def create_merchant(body: MerchantIn, user=Depends(current_user), db=Depends(db_dep)):
    if await db.merchants.count_documents({"owner_id": user["_id"]}) >= MAX_PROGRAMS:
        raise HTTPException(409, f"an account can create up to {MAX_PROGRAMS} programs")
    base = slugify(body.name) or "program"
    key, key_hash, hint = new_secret_key()
    now = datetime.now(UTC)
    merchant = {
        "_id": new_id("mer"),
        "name": body.name.strip(),
        "website": str(body.website).rstrip("/"),
        "owner_id": user["_id"],
        "member_ids": [user["_id"]],
        "public_key": f"pk_kr_{random_id(24)}",
        "secret_key_hash": key_hash,
        "secret_key_hint": hint,
        "settings": dict(DEFAULT_SETTINGS),
        "plan": plans.new_trial(now),
        "created_at": now,
    }
    for attempt in range(5):
        merchant["slug"] = base if attempt == 0 else f"{base}-{random_id(4).lower()}"
        try:
            await db.merchants.insert_one(merchant)
            break
        except DuplicateKeyError:
            continue
    else:
        raise HTTPException(409, "could not pick a unique program URL")
    await db.campaigns.insert_one(
        {
            "_id": new_id("cmp"),
            "merchant_id": merchant["_id"],
            "name": "Default",
            "rule": {"type": "percent", "bps": 3000},
            "duration": {"mode": "months", "months": 12},
            "hold_days": 30,
            "min_payout_cents": 5000,
            "is_default": True,
            "created_at": now,
        }
    )
    return {"merchant": merchant_out(merchant), "secret_key": key}


@router.get("")
async def get_merchant(m=Depends(current_merchant)):
    return merchant_out(m)


class SettingsIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    website: HttpUrl | None = None
    cookie_days: int | None = Field(default=None, ge=1, le=365)
    param_names: list[str] | None = Field(default=None, min_length=1, max_length=5)
    auto_approve: bool | None = None
    affiliate_links: bool | None = None
    require_tax_form: bool | None = None
    reject_self_referrals: bool | None = None
    attribution: Literal["first", "last"] | None = None
    emails: dict[str, bool] | None = None
    display_currency: str | None = None


@router.patch("")
async def update_merchant(body: SettingsIn, m=Depends(current_merchant), db=Depends(db_dep)):
    s: dict = {}
    if body.name is not None:
        s["name"] = body.name.strip()
    if body.website is not None:
        s["website"] = str(body.website).rstrip("/")
    for k in ("cookie_days", "auto_approve", "affiliate_links", "require_tax_form", "reject_self_referrals", "attribution"):
        if getattr(body, k) is not None:
            s[f"settings.{k}"] = getattr(body, k)
    if body.display_currency is not None:
        if body.display_currency.lower() not in fx.DISPLAY_CURRENCIES:
            raise HTTPException(422, f"unsupported display currency: {body.display_currency}")
        s["settings.display_currency"] = body.display_currency.lower()
    for k, on in (body.emails or {}).items():
        if k not in EMAIL_KINDS:
            raise HTTPException(422, f"unknown email: {k}")
        s[f"settings.emails.{k}"] = on
    if body.param_names is not None:
        names = [slugify(p).replace("-", "_") for p in body.param_names if slugify(p)]
        if not names:
            raise HTTPException(422, "need at least one URL parameter name")
        s["settings.param_names"] = names
    if s:
        await db.merchants.update_one({"_id": m["_id"]}, {"$set": s})
    return merchant_out(await db.merchants.find_one({"_id": m["_id"]}))


class BrandingIn(BaseModel):
    logo_url: HttpUrl | None = None
    favicon_url: HttpUrl | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    headline: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)
    welcome_message: str = Field(default="", max_length=1000)
    terms_url: HttpUrl | None = None
    reply_to: str | None = Field(default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.put("/branding")
async def update_branding(body: BrandingIn, m=Depends(current_merchant), db=Depends(db_dep)):
    # Fields left out keep their value, so the terms page and the logo upload can each save their own part.
    sent = {k: (str(v) if isinstance(v, HttpUrl) else v) for k, v in body.model_dump().items() if k in body.model_fields_set}
    branding = {k: v for k, v in ((m.get("branding") or {}) | sent).items() if v}
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"branding": branding}})
    return merchant_out({**m, "branding": branding})


class TermsIn(BaseModel):
    title: str = Field(default="Terms of Service", max_length=120)
    html: str = Field(default="", max_length=terms.MAX_HTML)
    # A terms page on the program's own site. When set, it is linked instead of the hosted page.
    external_url: HttpUrl | None = None


@router.put("/terms")
async def update_terms(body: TermsIn, m=Depends(current_merchant), db=Depends(db_dep)):
    """Empty content removes the hosted page; an external terms URL in branding still works."""
    html = terms.clean(body.html)
    doc = {"title": body.title.strip() or "Terms of Service", "html": html, "updated_at": datetime.now(UTC)} if html else None
    branding = {k: v for k, v in (m.get("branding") or {}).items() if k != "terms_url"} | ({"terms_url": str(body.external_url)} if body.external_url else {})
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"branding": branding, **({"terms": doc} if doc else {})}, **({} if doc else {"$unset": {"terms": ""}})})
    await audit.record(db, m["_id"], "terms.updated", m["_id"], removed=not html, external_url=branding.get("terms_url"))
    return merchant_out({k: v for k, v in m.items() if k != "terms"} | {"branding": branding} | ({"terms": doc} if doc else {}))


# ---------- custom portal domain ----------

HOST = r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"


class DomainIn(BaseModel):
    host: str = Field(max_length=253)


def _cname_ok(host: str) -> tuple[bool, str]:
    """True when the host is a CNAME to Kickrail's portal target."""
    import dns.exception
    import dns.resolver

    target = get_settings().portal_cname_target.rstrip(".").lower()
    if host.endswith(".localhost") and get_settings().public_url.startswith("http://localhost"):
        return True, "local development host"
    try:
        answer = dns.resolver.resolve(host, "CNAME", lifetime=5)
    except dns.resolver.NXDOMAIN:
        return False, f"{host} does not exist in DNS yet"
    except dns.resolver.NoAnswer:
        # Some DNS hosts flatten the CNAME into A records; accept those if they match ours.
        return _a_records_match(host, target)
    except dns.resolver.NoNameservers:
        return False, f"{host} has no CNAME record"
    except dns.exception.DNSException as e:
        return False, f"DNS lookup failed: {e.__class__.__name__}"
    found = [str(r.target).rstrip(".").lower() for r in answer]
    return (target in found, "verified" if target in found else f"{host} points to {', '.join(found)}, not {target}")


def _a_records_match(host: str, target: str) -> tuple[bool, str]:
    import dns.exception
    import dns.resolver

    try:
        theirs = {r.address for r in dns.resolver.resolve(host, "A", lifetime=5)}
        ours = {r.address for r in dns.resolver.resolve(target, "A", lifetime=5)}
    except dns.exception.DNSException:
        return False, f"{host} has no CNAME record"
    if theirs and theirs <= ours:
        return True, "verified"
    return False, f"{host} has no CNAME record pointing to {target}"


async def _https_ok(host: str) -> tuple[bool, str]:
    """Open the portal over HTTPS. The first request is also what makes the portal
    proxy fetch a certificate, so this can take a few seconds."""
    if host.endswith(".localhost"):
        return True, "local development host"
    import httpx

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            res = await client.get(f"https://{host}/", follow_redirects=False)
    except httpx.HTTPError as e:
        return False, f"HTTPS isn't working yet ({e.__class__.__name__}). Certificates usually take under a minute; check again shortly."
    if res.status_code >= 500:
        return False, f"{host} answered with an error ({res.status_code})"
    return True, "HTTPS is working"


def _clean_host(raw: str) -> str:
    import re

    host = raw.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not re.match(HOST, host) and not host.endswith(".localhost"):
        raise HTTPException(422, "enter a hostname like affiliates.example.com")
    own = urlsplit(get_settings().public_url).hostname or ""
    if host == own or host.endswith(f".{own}"):
        raise HTTPException(422, "use a domain you own")
    return host


def domain_out(d: dict) -> dict:
    """A portal domain for API and agent callers: its state and the DNS record it needs."""
    status = "live" if d.get("verified") and d.get("https") else "waiting_for_https" if d.get("verified") else "not_verified"
    host = d["host"]
    return {
        "host": host,
        "status": status,
        "primary": bool(d.get("primary")),
        "detail": d.get("https_detail") if status == "waiting_for_https" else d.get("detail"),
        "dns_record": {"type": "CNAME", "name": host, "value": get_settings().portal_cname_target},
        "join_url": f"https://{host}/",
        "added_at": d.get("added_at"),
        "verified_at": d.get("verified_at"),
        "checked_at": d.get("checked_at"),
    }


def _domain(m: dict, host: str) -> dict:
    d = next((d for d in m.get("portal_domains") or [] if d["host"] == host.lower()), None)
    if not d:
        raise HTTPException(404, "that domain isn't on this program")
    return d


@router.post("/domains")
async def add_domain(body: DomainIn, m=Depends(current_merchant), db=Depends(db_dep)):
    host = _clean_host(body.host)
    domains = m.get("portal_domains") or []
    if any(d["host"] == host for d in domains):
        raise HTTPException(409, "that domain is already on this program")
    plans.require_room(m, "domains", len(domains))
    if await db.merchants.find_one({"portal_domains.host": host}, {"_id": 1}):
        raise HTTPException(409, "another program already uses that domain")
    domain = {"host": host, "verified": False, "added_at": datetime.now(UTC), "primary": not domains}
    try:
        res = await db.merchants.update_one({"_id": m["_id"], "portal_domains.host": {"$ne": host}}, {"$push": {"portal_domains": domain}})
    except DuplicateKeyError:
        raise HTTPException(409, "another program already uses that domain")
    if not res.modified_count:
        raise HTTPException(409, "that domain is already on this program")
    return await _check_domain(db, {**m, "portal_domains": [*domains, domain]}, host)


@router.post("/domains/{host}/verify")
async def verify_domain(host: str, m=Depends(current_merchant), db=Depends(db_dep)):
    _domain(m, host)
    return await _check_domain(db, m, host.lower())


async def _check_domain(db, m: dict, host: str) -> dict:
    import asyncio

    domain = _domain(m, host)
    ok, detail = await asyncio.to_thread(_cname_ok, host)
    now = datetime.now(UTC)
    domain = {**domain, "verified": ok, "checked_at": now, "detail": detail} | ({"verified_at": domain.get("verified_at") or now} if ok else {"https": False})
    # Saved before the HTTPS check: the proxy only gets a certificate for verified domains.
    await db.merchants.update_one({"_id": m["_id"], "portal_domains.host": host}, {"$set": {"portal_domains.$": domain}})
    if ok:
        https, https_detail = await _https_ok(host)
        domain = {**domain, "https": https, "https_detail": https_detail}
        await db.merchants.update_one({"_id": m["_id"], "portal_domains.host": host}, {"$set": {"portal_domains.$.https": https, "portal_domains.$.https_detail": https_detail}})
    fresh = await db.merchants.find_one({"_id": m["_id"]})
    return {"domain": domain, "merchant": merchant_out(fresh or m)}


@router.post("/domains/{host}/primary")
async def make_primary(host: str, m=Depends(current_merchant), db=Depends(db_dep)):
    _domain(m, host)
    domains = [{**d, "primary": d["host"] == host.lower()} for d in m.get("portal_domains") or []]
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"portal_domains": domains}})
    return merchant_out({**m, "portal_domains": domains})


@router.delete("/domains/{host}")
async def remove_domain(host: str, m=Depends(current_merchant), db=Depends(db_dep)):
    gone = _domain(m, host)
    domains = [d for d in m.get("portal_domains") or [] if d["host"] != gone["host"]]
    if gone.get("primary") and domains:
        # The next verified one (else the oldest) takes over links and emails.
        nxt = next((d for d in domains if d.get("verified")), domains[0])
        domains = [{**d, "primary": d is nxt} for d in domains]
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"portal_domains": domains}})
    return {"ok": True}


@router.post("/rotate-secret")
async def rotate_secret(m=Depends(current_merchant), db=Depends(db_dep)):
    key, key_hash, hint = new_secret_key()
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"secret_key_hash": key_hash, "secret_key_hint": hint}})
    return {"secret_key": key}


# ---------- Stripe connection ----------


class StripeConnectIn(BaseModel):
    restricted_key: str = Field(pattern=r"^(rk|sk)_(test|live)_[A-Za-z0-9]+$")


async def _one_program_per_account(db, m: dict, account_id: str, livemode: bool, oauth: bool = False) -> None:
    """Two programs on one live Stripe account would both receive every sale and fight
    over the same promotion codes; test programs may share a sandbox. One-click
    connections can never share, because their events are routed by account."""
    clashes = ([{"stripe.livemode": True}] if livemode else []) + ([{"stripe.oauth": True}] if oauth else [])
    if not clashes:
        return
    other = await db.merchants.find_one({"_id": {"$ne": m["_id"]}, "stripe.account_id": account_id, "$or": clashes}, {"name": 1})
    if other:
        raise HTTPException(409, f"That Stripe account is already connected to {other['name']}. Disconnect it there first, or sell both products from one program with product rules.")


@router.post("/stripe")
async def connect_stripe(body: StripeConnectIn, m=Depends(current_merchant), db=Depends(db_dep), make=Depends(merchant_key_client), factory=Depends(merchant_api_factory)):
    api = make(body.restricted_key)
    livemode = "_live_" in body.restricted_key
    try:
        acct = await api.account()
    except Exception as e:
        log.warning("stripe connect failed for %s: %s", m["_id"], e)
        raise HTTPException(400, f"Stripe rejected the key: {getattr(e, 'user_message', None) or e}")
    await _one_program_per_account(db, m, acct["id"], livemode)
    try:
        if get_settings().dev_webhook_secret:
            endpoint_id, webhook_secret = None, get_settings().dev_webhook_secret
        else:
            endpoint_id, webhook_secret = await api.create_webhook(f"{get_settings().public_url}/api/webhooks/stripe/{m['_id']}")
    except Exception as e:
        log.warning("stripe connect failed for %s: %s", m["_id"], e)
        raise HTTPException(400, f"Stripe rejected the key: {getattr(e, 'user_message', None) or e}")
    await _drop_old_webhook(m, factory)
    stripe = {
        "account_id": acct["id"],
        "account_name": acct["name"],
        "livemode": livemode,
        "key_enc": encrypt(body.restricted_key),
        "webhook_endpoint_id": endpoint_id,
        "webhook_secret_enc": encrypt(webhook_secret),
        "connected_at": datetime.now(UTC),
    }
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"stripe": stripe}})
    await audit.record(db, m["_id"], "stripe.connected", m["_id"], account_id=stripe.get("account_id"), livemode=stripe.get("livemode"))
    await stripe_sync.mark_merchant(db, m["_id"])
    return merchant_out({**m, "stripe": stripe})


async def _drop_old_webhook(m: dict, factory) -> None:
    old = m.get("stripe")
    if old and old.get("webhook_endpoint_id"):
        try:
            await factory(m).delete_webhook(old["webhook_endpoint_id"])
        except Exception:
            log.warning("could not delete old webhook for %s", m["_id"], exc_info=True)


def _oauth_state(m: dict, user: dict) -> str:
    now = datetime.now(UTC)
    return jwt.encode({"p": "stripe_oauth", "m": m["_id"], "u": user["_id"], "exp": now + timedelta(minutes=30)}, get_settings().app_secret, algorithm="HS256")


@router.get("/stripe/oauth")
async def stripe_oauth_start(m=Depends(current_merchant), user=Depends(current_user), oauth=Depends(stripe_oauth)):
    """Where the "Connect with Stripe" button goes."""
    return {"url": oauth.authorize_url(_oauth_state(m, user), f"{get_settings().public_url}/dashboard/stripe/callback", user.get("email"))}


class StripeOAuthIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=2000)


@router.post("/stripe/oauth")
async def stripe_oauth_finish(body: StripeOAuthIn, user=Depends(current_user), db=Depends(db_dep), oauth=Depends(stripe_oauth), make=Depends(merchant_account_client), factory=Depends(merchant_api_factory)):
    try:
        st = jwt.decode(body.state, get_settings().app_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(400, "This Stripe link has expired. Click Connect with Stripe again.")
    if st.get("p") != "stripe_oauth" or st.get("u") != user["_id"]:
        raise HTTPException(400, "This Stripe link was started by someone else. Click Connect with Stripe again.")
    # The state names the program, so a second tab switching programs can't redirect the connection.
    m = await db.merchants.find_one({"_id": st["m"], "member_ids": user["_id"]})
    if not m:
        raise HTTPException(404, "program not found")
    try:
        tok = await oauth.token(body.code)
        acct = await make(tok["account_id"]).account()
    except Exception as e:
        log.warning("stripe oauth failed for %s: %s", m["_id"], e)
        raise HTTPException(400, f"Stripe didn't accept the connection: {getattr(e, 'user_message', None) or e}")
    await _one_program_per_account(db, m, acct["id"], tok["livemode"], oauth=True)
    await _drop_old_webhook(m, factory)
    stripe = {"oauth": True, "account_id": acct["id"], "account_name": acct["name"], "livemode": tok["livemode"], "connected_at": datetime.now(UTC)}
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"stripe": stripe}})
    audit.as_user(user)
    await audit.record(db, m["_id"], "stripe.connected", m["_id"], account_id=acct["id"], livemode=tok["livemode"], oauth=True)
    await stripe_sync.mark_merchant(db, m["_id"])
    return merchant_out({**m, "stripe": stripe})


@router.delete("/stripe")
async def disconnect_stripe(m=Depends(current_merchant), db=Depends(db_dep), factory=Depends(merchant_api_factory), oauth=Depends(stripe_oauth_optional)):
    if m.get("stripe", {}).get("oauth") and oauth:
        try:
            await oauth.deauthorize(m["stripe"]["account_id"])
        except Exception:
            log.warning("could not deauthorize stripe for %s", m["_id"], exc_info=True)
    if m.get("stripe", {}).get("webhook_endpoint_id"):
        try:
            await factory(m).delete_webhook(m["stripe"]["webhook_endpoint_id"])
        except Exception:
            log.warning("could not delete webhook for %s", m["_id"], exc_info=True)
    await db.merchants.update_one({"_id": m["_id"]}, {"$unset": {"stripe": ""}})
    await audit.record(db, m["_id"], "stripe.disconnected", m["_id"], account_id=(m.get("stripe") or {}).get("account_id"))
    return {"ok": True}


@router.get("/stripe/coupons")
async def stripe_coupons(m=Depends(current_merchant), factory=Depends(merchant_api_factory)):
    if not m.get("stripe"):
        raise HTTPException(400, "connect Stripe first")
    return await factory(m).list_coupons()


# ---------- campaigns ----------


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    rule_type: Literal["percent", "flat"]
    percent: float | None = Field(default=None, gt=0, le=100)
    flat_cents: int | None = Field(default=None, gt=0)
    currency: str = "usd"
    duration_mode: Literal["once", "months", "forever"]
    months: int | None = Field(default=None, ge=1, le=120)
    hold_days: int = Field(ge=0, le=180)
    min_payout_cents: int = Field(ge=0)
    stripe_coupon_id: str | None = None
    lead_bounty_cents: int = Field(default=0, ge=0, le=1_000_000)
    lead_bounty_currency: str = "usd"
    product_rules: list["ProductRuleIn"] = Field(default_factory=list, max_length=50)
    # Public campaigns get their own join page at /join/<program>/<slug>; private ones are invite-only.
    public: bool = False
    slug: str | None = Field(default=None, max_length=40)
    # Where this campaign's default affiliate links point, instead of the program website.
    landing_url: str | None = Field(default=None, max_length=1000)
    # "custom": the reward isn't cash. The rule fields above are then ignored and no commissions are made.
    reward_type: Literal["cash", "custom"] = "cash"
    affiliate_reward: str = Field(default="", max_length=120)
    affiliate_reward_on: Literal["signup", "first_payment", "every_payment"] = "first_payment"
    affiliate_reward_limit: Literal["once", "per_referral"] = "per_referral"
    customer_reward: str = Field(default="", max_length=120)
    customer_reward_on: Literal["signup", "first_payment"] = "signup"


class RuleIn(BaseModel):
    type: Literal["percent", "flat", "none"]
    percent: float | None = Field(default=None, gt=0, le=100)
    flat_cents: int | None = Field(default=None, gt=0)
    currency: str = "usd"


class ProductRuleIn(BaseModel):
    match: Literal["product", "price"]
    id: str = Field(pattern=r"^(prod|price)_[A-Za-z0-9]+$")
    label: str = Field(default="", max_length=80)
    rule: RuleIn


def rule_doc(r: RuleIn) -> dict:
    if r.type == "percent":
        if r.percent is None:
            raise HTTPException(422, "percent is required")
        return {"type": "percent", "bps": round(r.percent * 100)}
    if r.type == "flat":
        if r.flat_cents is None:
            raise HTTPException(422, "flat amount is required")
        return {"type": "flat", "cents": r.flat_cents, "currency": r.currency.lower()}
    return {"type": "none"}


CAMPAIGN_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
# /join/<program>/terms is the hosted terms page.
RESERVED_CAMPAIGN_SLUGS = {"terms"}


def _campaign_fields(b: CampaignIn, m: dict) -> dict:
    if b.rule_type == "percent":
        if b.percent is None:
            raise HTTPException(422, "percent is required")
        rule = {"type": "percent", "bps": round(b.percent * 100)}
    else:
        if b.flat_cents is None:
            raise HTTPException(422, "flat amount is required")
        rule = {"type": "flat", "cents": b.flat_cents, "currency": b.currency.lower()}
    if b.duration_mode == "months":
        if not b.months:
            raise HTTPException(422, "months is required")
        duration = {"mode": "months", "months": b.months}
    else:
        duration = {"mode": b.duration_mode}
    for pr in b.product_rules:
        if not pr.id.startswith(f"{pr.match}_" if pr.match == "price" else "prod_"):
            raise HTTPException(422, f"{pr.id} is not a {pr.match} id")
    slug = (b.slug or "").strip().lower() or (slugify(b.name)[:40] if b.public else "")
    if slug and not CAMPAIGN_SLUG.match(slug):
        raise HTTPException(422, "join page names are 2-40 lowercase letters, digits or -")
    if slug in RESERVED_CAMPAIGN_SLUGS:
        raise HTTPException(422, f"{slug} is used by Kickrail's own pages; pick another join page name")
    try:
        landing = check_landing(m, b.landing_url)
    except AffiliateError as e:
        raise HTTPException(e.status, str(e))
    reward = None
    if b.reward_type == "custom":
        if not b.affiliate_reward.strip():
            raise HTTPException(422, "describe what the affiliate gets")
        reward = {
            "type": "custom",
            "affiliate": {"description": b.affiliate_reward.strip(), "on": b.affiliate_reward_on, "limit": b.affiliate_reward_limit},
            "customer": {"description": b.customer_reward.strip(), "on": b.customer_reward_on} if b.customer_reward.strip() else None,
        }
    return {
        "reward": reward,
        "public": b.public,
        "slug": slug or None,
        "landing_url": landing,
        "name": b.name.strip(),
        "rule": rule,
        "duration": duration,
        "hold_days": b.hold_days,
        "min_payout_cents": b.min_payout_cents,
        "stripe_coupon_id": b.stripe_coupon_id or None,
        "lead_bounty": {"cents": b.lead_bounty_cents, "currency": b.lead_bounty_currency.lower()} if b.lead_bounty_cents and not reward else None,
        "product_rules": [{"match": pr.match, "id": pr.id, "label": pr.label.strip(), "rule": rule_doc(pr.rule)} for pr in b.product_rules],
    }


def campaign_out(c: dict, m: dict) -> dict:
    return {
        **out(c),
        "public": bool(c.get("public")),
        "slug": c.get("slug"),
        "landing_url": c.get("landing_url"),
        # The main join page always signs people up to the default campaign.
        "join_url": join_url(m, c) if c.get("public") and c.get("slug") else (join_url(m) if c.get("is_default") else None),
        "description": describe_rule(c),
        "lead_bounty": c.get("lead_bounty"),
        "reward": c.get("reward"),
        "product_rules": [{**r, "description": describe_rate(r["rule"])} for r in c.get("product_rules") or []],
    }


@router.get("/campaigns")
async def list_campaigns(m=Depends(current_merchant), db=Depends(db_dep)):
    return [campaign_out(c, m) async for c in db.campaigns.find({"merchant_id": m["_id"]}).sort("created_at", 1)]


@router.post("/campaigns")
async def create_campaign(body: CampaignIn, m=Depends(current_merchant), db=Depends(db_dep)):
    plans.require_room(m, "campaigns", await db.campaigns.count_documents({"merchant_id": m["_id"]}))
    if body.stripe_coupon_id:
        plans.require(m, "creator_codes")
    c = {"_id": new_id("cmp"), "merchant_id": m["_id"], **_campaign_fields(body, m), "is_default": False, "created_at": datetime.now(UTC)}
    try:
        await db.campaigns.insert_one(c)
    except DuplicateKeyError:
        raise HTTPException(409, "another campaign already uses that join page name")
    return campaign_out(c, m)


@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, body: CampaignIn, m=Depends(current_merchant), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    # Changes apply to future commissions only; earned ones keep their amounts.
    before = await db.campaigns.find_one({"_id": campaign_id, "merchant_id": m["_id"]}, {"stripe_coupon_id": 1}) or {}
    new_coupon = (before.get("stripe_coupon_id") or None) != (body.stripe_coupon_id or None)
    if new_coupon and body.stripe_coupon_id:
        plans.require(m, "creator_codes")
    try:
        res = await db.campaigns.find_one_and_update({"_id": campaign_id, "merchant_id": m["_id"]}, {"$set": _campaign_fields(body, m)}, return_document=True)
    except DuplicateKeyError:
        raise HTTPException(409, "another campaign already uses that join page name")
    if not res:
        raise HTTPException(404, "campaign not found")
    # A swapped or removed coupon switches off the old promotion codes.
    warning = await sync_campaign_codes(db, m, campaign_id, factory, replace=bool(before.get("stripe_coupon_id"))) if new_coupon else None
    return {**campaign_out(res, m), "warning": warning}


@router.post("/campaigns/{campaign_id}/default")
async def make_default(campaign_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    if not await db.campaigns.find_one({"_id": campaign_id, "merchant_id": m["_id"]}):
        raise HTTPException(404, "campaign not found")
    await db.campaigns.update_many({"merchant_id": m["_id"]}, {"$set": {"is_default": False}})
    await db.campaigns.update_one({"_id": campaign_id}, {"$set": {"is_default": True}})
    return {"ok": True}


# ---------- affiliates ----------


async def _affiliate_stats(db, merchant_id: str, affiliate_ids: list[str]) -> dict[str, dict]:
    # Money is kept per currency ({"usd": 1200, "inr": 99900}); adding rupees to dollars means nothing.
    stats: dict[str, dict] = {a: {"clicks": 0, "leads": 0, "customers": 0, "earned": {}, "paid": {}} for a in affiliate_ids}
    async for row in await db.clicks.aggregate([{"$match": {"merchant_id": merchant_id, "affiliate_id": {"$in": affiliate_ids}, "test": False}}, {"$group": {"_id": "$affiliate_id", "n": {"$sum": 1}}}]):
        if row["_id"] in stats:
            stats[row["_id"]]["clicks"] = row["n"]
    async for row in await db.referrals.aggregate([{"$match": {"merchant_id": merchant_id, "affiliate_id": {"$in": affiliate_ids}, "test": {"$ne": True}}}, {"$group": {"_id": {"a": "$affiliate_id", "s": "$status"}, "n": {"$sum": 1}}}]):
        a = row["_id"]["a"]
        if a in stats:
            stats[a]["leads"] += row["n"]
            if row["_id"]["s"] == "customer":
                stats[a]["customers"] += row["n"]
    async for row in await db.commissions.aggregate(
        [{"$match": {"merchant_id": merchant_id, "status": {"$ne": "void"}}}, {"$group": {"_id": {"a": "$affiliate_id", "s": "$status", "cur": "$currency"}, "c": {"$sum": "$amount_cents"}}}]
    ):
        a, cur = row["_id"]["a"], row["_id"]["cur"]
        if a in stats:
            stats[a]["earned"][cur] = stats[a]["earned"].get(cur, 0) + row["c"]
            if row["_id"]["s"] == "paid":
                stats[a]["paid"][cur] = stats[a]["paid"].get(cur, 0) + row["c"]
    return stats


async def _affiliate_rows(db, m: dict, affs: list[dict]) -> list[dict]:
    ids = [a["_id"] for a in affs]
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [a["user_id"] for a in affs]}})}
    stats = await _affiliate_stats(db, m["_id"], ids)
    campaigns = {c["_id"]: c async for c in db.campaigns.find({"merchant_id": m["_id"]}, {"landing_url": 1, "name": 1})}
    links: dict[str, list] = {}
    async for l in db.affiliate_links.find({"merchant_id": m["_id"], "affiliate_id": {"$in": ids}}).sort("created_at", 1):
        links.setdefault(l["affiliate_id"], []).append(link_obj(m, l))
    codes: dict[str, list] = {}
    async for c in db.affiliate_codes.find({"merchant_id": m["_id"], "affiliate_id": {"$in": ids}}).sort("created_at", 1):
        codes.setdefault(c["affiliate_id"], []).append(code_obj(c))
    return [
        {
            **out(a, "metadata"),
            "name": users.get(a["user_id"], {}).get("name", ""),
            "email": users.get(a["user_id"], {}).get("email", ""),
            "campaign_name": campaigns.get(a["campaign_id"], {}).get("name", ""),
            "payouts_enabled": bool(users.get(a["user_id"], {}).get("payouts_enabled")),
            "can_be_paid": can_be_paid(users.get(a["user_id"], {})),
            "tax_form": (users.get(a["user_id"], {}).get("tax_info") or {}).get("form"),
            "link": affiliate_url(m, a["token"], campaigns.get(a["campaign_id"], {}).get("landing_url")),
            "links": links.get(a["_id"], []),
            "codes": codes.get(a["_id"], []),
            "rate_override_description": describe_rate(a["rate_override"]) if a.get("rate_override") else None,
            **stats[a["_id"]],
        }
        for a in affs
    ]


@router.get("/affiliates")
async def list_affiliates(
    campaign_id: str | None = None,
    status: Literal["pending", "approved", "rejected"] | None = None,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1, le=10_000),
    m=Depends(current_merchant),
    db=Depends(db_dep),
):
    """A page of affiliates, newest first. A program can have tens of thousands
    (every customer, on a customer-referral campaign), so this never returns them all."""
    base: dict = {"merchant_id": m["_id"]}
    query = dict(base)
    if campaign_id:
        query["campaign_id"] = campaign_id
    if status:
        query["status"] = status
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["_id"] = {"$in": await _matching_affiliates(db, m["_id"], rx)}
    affs, total = await _page(db.affiliates, query, page)
    by_campaign = {row["_id"]: row["n"] async for row in await db.affiliates.aggregate([{"$match": base}, {"$group": {"_id": "$campaign_id", "n": {"$sum": 1}}}])}
    return {"items": await _affiliate_rows(db, m, affs), "total": total, "page": page, "page_size": PAGE_SIZE, "by_campaign": by_campaign}


@router.get("/affiliates/{affiliate_id}")
async def get_affiliate(affiliate_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    a = await db.affiliates.find_one({"_id": affiliate_id, "merchant_id": m["_id"]})
    if not a:
        raise HTTPException(404, "affiliate not found")
    return (await _affiliate_rows(db, m, [a]))[0]


class AffiliateAdd(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    campaign_id: str | None = None
    send_welcome_email: bool = True


@router.post("/affiliates")
async def add_affiliate(body: AffiliateAdd, m=Depends(current_merchant), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    try:
        aff, created = await add_by_email(db, m, body.email, body.name, factory, status="approved", campaign_id=body.campaign_id, send_welcome=body.send_welcome_email)
    except AffiliateError as e:
        raise HTTPException(e.status, str(e))
    if not created:
        raise HTTPException(409, "they're already an affiliate in this program")
    return out(aff)


class AffiliatePatch(BaseModel):
    status: Literal["pending", "approved", "rejected"] | None = None
    campaign_id: str | None = None
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{3,20}$")
    token: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{3,32}$")
    # A rule replaces the campaign rate for this affiliate; {"type": null} style clearing uses clear_rate_override.
    rate_override: RuleIn | None = None
    clear_rate_override: bool = False
    metadata: dict[str, str] | None = None


async def patch_affiliate(db, m: dict, aff: dict, body: AffiliatePatch, factory) -> dict:
    """Shared by the dashboard and PATCH /v1/affiliates/{id}."""
    s: dict = {}
    unset: dict = {}
    if body.status:
        s["status"] = body.status
    if body.campaign_id:
        if not await db.campaigns.find_one({"_id": body.campaign_id, "merchant_id": m["_id"]}):
            raise HTTPException(404, "campaign not found")
        s["campaign_id"] = body.campaign_id
    if body.code and body.code.upper() != aff.get("code"):
        if await db.affiliate_codes.find_one({"merchant_id": m["_id"], "code": body.code.upper()}):
            raise HTTPException(409, "another affiliate already uses that code")
        s["code"] = body.code.upper()
    if body.token and body.token != aff["token"]:
        if await db.affiliate_links.find_one({"merchant_id": m["_id"], "token": body.token}):
            raise HTTPException(409, "that link name is taken in this program")
        s["token"] = body.token
    if body.rate_override:
        s["rate_override"] = rule_doc(body.rate_override)
    elif body.clear_rate_override:
        unset["rate_override"] = ""
    if body.metadata is not None:
        s["metadata"] = body.metadata
    if s or unset:
        try:
            await db.affiliates.update_one({"_id": aff["_id"]}, {"$set": s} | ({"$unset": unset} if unset else {}))
        except DuplicateKeyError:
            raise HTTPException(409, "another affiliate already uses that code or link name")
    new = await db.affiliates.find_one({"_id": aff["_id"]})
    warning = await sync_promotion_code(db, m, new, factory)
    if s or unset:
        await notify.affiliate_updated(db, m, new, aff["status"] if new["status"] != aff["status"] else None)
        if new["status"] != aff["status"]:
            await audit.record(db, m["_id"], f"affiliate.{new['status']}", aff["_id"], previous=aff["status"])
        money = {k: (aff.get(k), new.get(k)) for k in ("campaign_id", "rate_override") if aff.get(k) != new.get(k)}
        if money:
            await audit.record(db, m["_id"], "affiliate.terms_changed", aff["_id"], **{k: {"from": a, "to": b} for k, (a, b) in money.items()})
    return {**out(new), "warning": warning}


@router.patch("/affiliates/{affiliate_id}")
async def update_affiliate(affiliate_id: str, body: AffiliatePatch, m=Depends(current_merchant), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    return await patch_affiliate(db, m, await _aff(db, m, affiliate_id), body, factory)


async def _aff(db, m: dict, affiliate_id: str) -> dict:
    aff = await db.affiliates.find_one({"_id": affiliate_id, "merchant_id": m["_id"]})
    if not aff:
        raise HTTPException(404, "affiliate not found")
    return aff


@router.get("/affiliates/{affiliate_id}/view")
async def view_as_affiliate(affiliate_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    """Exactly what this affiliate sees in their portal, for support and checking setup."""
    aff = await _aff(db, m, affiliate_id)
    user = await db.users.find_one({"_id": aff["user_id"]}) or {}
    return {**await affiliate_view(db, m, aff, user), "affiliate": {"name": user.get("name", ""), "email": user.get("email", "")}}


class MerchantLinkIn(BaseModel):
    token: str = Field(min_length=3, max_length=32)
    landing_url: str | None = Field(default=None, max_length=1000)
    label: str = Field(default="", max_length=80)


@router.post("/affiliates/{affiliate_id}/links")
async def create_link(affiliate_id: str, body: MerchantLinkIn, m=Depends(current_merchant), db=Depends(db_dep)):
    try:
        return await add_link(db, m, await _aff(db, m, affiliate_id), body.token, body.landing_url, body.label)
    except AffiliateError as e:
        raise HTTPException(e.status, str(e))


@router.delete("/affiliates/{affiliate_id}/links/{link_id}")
async def delete_link(affiliate_id: str, link_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    res = await db.affiliate_links.delete_one({"_id": link_id, "affiliate_id": affiliate_id, "merchant_id": m["_id"]})
    if not res.deleted_count:
        raise HTTPException(404, "link not found")
    return {"ok": True}


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9]{3,20}$")


@router.post("/affiliates/{affiliate_id}/codes")
async def create_code(affiliate_id: str, body: CodeIn, m=Depends(current_merchant), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    plans.require(m, "creator_codes")
    try:
        code, warning = await add_code(db, m, await _aff(db, m, affiliate_id), body.code, factory)
    except AffiliateError as e:
        raise HTTPException(e.status, str(e))
    return {**code, "warning": warning}


@router.delete("/affiliates/{affiliate_id}/codes/{code_id}")
async def delete_code(affiliate_id: str, code_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    # The Stripe promotion code stays; a redemption of it simply no longer resolves to anyone.
    res = await db.affiliate_codes.delete_one({"_id": code_id, "affiliate_id": affiliate_id, "merchant_id": m["_id"]})
    if not res.deleted_count:
        raise HTTPException(404, "code not found")
    return {"ok": True}


# ---------- referrals & commissions ----------


PAGE_SIZE = 50


async def _page(coll, query: dict, page: int) -> tuple[list[dict], int]:
    total = await coll.count_documents(query)
    rows = await coll.find(query).sort([("created_at", -1), ("_id", -1)]).skip((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).to_list(None)
    return rows, total


async def _matching_affiliates(db, merchant_id: str, rx: dict) -> list[str]:
    """Affiliates whose name, email or link name matches, for searching their referrals and commissions."""
    affs = await db.affiliates.find({"merchant_id": merchant_id}, {"user_id": 1, "token": 1}).to_list(None)
    users = {u["_id"] async for u in db.users.find({"_id": {"$in": [a["user_id"] for a in affs]}, "$or": [{"name": rx}, {"email": rx}]}, {"_id": 1})}
    tokens = {a["affiliate_id"] async for a in db.affiliate_links.find({"merchant_id": merchant_id, "token": rx}, {"affiliate_id": 1})}
    return [a["_id"] for a in affs if a["user_id"] in users or a["_id"] in tokens or re.search(rx["$regex"], a.get("token", ""), re.I)]


@router.get("/referrals")
async def list_referrals(
    flagged: bool = False,
    status: Literal["lead", "customer"] | None = None,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1, le=10_000),
    m=Depends(current_merchant),
    db=Depends(db_dep),
):
    query: dict = {"merchant_id": m["_id"]}
    if flagged:
        query["flags.0"] = {"$exists": True}
        query["flags_cleared"] = {"$ne": True}
    if status:
        query["status"] = status
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"email": rx}, {"stripe_customer_id": rx}, {"external_user_id": rx}, {"via.token": rx}, {"via.code": rx}, {"affiliate_id": {"$in": await _matching_affiliates(db, m["_id"], rx)}}]
    refs, total = await _page(db.referrals, query, page)
    names = await _affiliate_names(db, m["_id"], [r["affiliate_id"] for r in refs])
    return {"items": [{**out(r), "affiliate_name": names.get(r["affiliate_id"], "")} for r in refs], "total": total, "page": page, "page_size": PAGE_SIZE}


@router.get("/referrals/{referral_id}")
async def get_referral(referral_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    r = await db.referrals.find_one({"_id": referral_id, "merchant_id": m["_id"]})
    if not r:
        raise HTTPException(404, "referral not found")
    aff = await db.affiliates.find_one({"_id": r["affiliate_id"], "merchant_id": m["_id"]}, {"user_id": 1, "token": 1})
    user = aff and await db.users.find_one({"_id": aff["user_id"]}, {"name": 1, "email": 1})
    campaign = r.get("campaign_id") and await db.campaigns.find_one({"_id": r["campaign_id"], "merchant_id": m["_id"]}, {"name": 1})
    # The visitor's IP hash and browser stay out: the merchant only needs where they came from.
    click = r.get("click_id") and await db.clicks.find_one({"_id": r["click_id"], "merchant_id": m["_id"]}, {"token": 1, "landing_url": 1, "referrer": 1, "created_at": 1})
    commissions = await db.commissions.find({"merchant_id": m["_id"], "referral_id": referral_id}).sort([("created_at", -1), ("_id", -1)]).to_list(None)
    name = (user or {}).get("name", "")
    return {
        **out(r),
        "affiliate_name": name,
        "affiliate": {"id": r["affiliate_id"], "name": name, "email": (user or {}).get("email", ""), "token": (aff or {}).get("token", "")},
        "campaign": out(campaign) if campaign else None,
        "click": out(click) if click else None,
        "commissions": [{**out(c), "affiliate_name": name} for c in commissions],
        "rewards": [out(w) async for w in db.rewards.find({"merchant_id": m["_id"], "referral_id": referral_id}).sort("created_at", -1)],
    }


@router.post("/referrals/{referral_id}/clear")
async def clear_flags(referral_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    async def clear(tdb) -> bool:
        res = await tdb.referrals.update_one({"_id": referral_id, "merchant_id": m["_id"]}, {"$set": {"flags_cleared": True}})
        if not res.matched_count:
            return False
        released = await tdb.commissions.update_many({"referral_id": referral_id, "held": True}, {"$set": {"held": False}})
        rewards_released = await rewards.release(tdb, m["_id"], await tdb.referrals.find_one({"_id": referral_id}))
        await audit.record(tdb, m["_id"], "referral.flags_cleared", referral_id, commissions_released=released.modified_count, rewards_released=rewards_released)
        async for c in tdb.commissions.find({"referral_id": referral_id}, {"_id": 1}):
            await notify.commission_updated(tdb, m["_id"], c["_id"])
        return True

    if not await run_in_transaction(db, clear):
        raise HTTPException(404, "referral not found")
    return {"ok": True}


@router.post("/referrals/{referral_id}/reject")
async def reject_referral(referral_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    async def reject(tdb) -> bool:
        res = await tdb.referrals.update_one({"_id": referral_id, "merchant_id": m["_id"]}, {"$set": {"flags_cleared": True, "rejected": True}})
        if not res.matched_count:
            return False
        voidable = {"referral_id": referral_id, "status": "pending", "payout_id": {"$exists": False}}
        ids = [c["_id"] async for c in tdb.commissions.find(voidable, {"_id": 1})]
        await tdb.commissions.update_many({"_id": {"$in": ids}}, {"$set": {"status": "void", "void_reason": "referral rejected", "amount_cents": 0}})
        voided_rewards = await rewards.void_unfulfilled(tdb, referral_id, "referral rejected")
        await audit.record(tdb, m["_id"], "referral.rejected", referral_id, commissions_voided=ids, rewards_voided=voided_rewards)
        for cid in ids:
            await notify.commission_updated(tdb, m["_id"], cid)
        return True

    if not await run_in_transaction(db, reject):
        raise HTTPException(404, "referral not found")
    return {"ok": True}


class DeleteIn(BaseModel):
    reason: str | None = Field(None, max_length=300)


@router.delete("/referrals/{referral_id}")
async def delete_referral(referral_id: str, body: DeleteIn | None = None, m=Depends(current_merchant), db=Depends(db_dep), factory=Depends(merchant_api_factory)):
    try:
        r, commissions = await deletion.delete_referral(db, m["_id"], referral_id, body.reason if body else None)
    except deletion.NotFound:
        raise HTTPException(404, "referral not found")
    except deletion.Blocked as e:
        raise HTTPException(409, str(e))
    if r.get("stripe_customer_id") and m.get("stripe"):
        try:  # don't leave the Stripe customer pointing at a referral that's gone
            await factory(m).update_customer_metadata(r["stripe_customer_id"], {k: "" for k in stripe_sync.customer_metadata(r, None)})
        except Exception:
            log.warning("clearing customer metadata failed for %s", r["_id"], exc_info=True)
    return {"ok": True, "commissions_deleted": len(commissions)}


@router.delete("/commissions/{commission_id}")
async def delete_commission(commission_id: str, body: DeleteIn | None = None, m=Depends(current_merchant), db=Depends(db_dep)):
    try:
        await deletion.delete_commission(db, m["_id"], commission_id, body.reason if body else None)
    except deletion.NotFound:
        raise HTTPException(404, "commission not found")
    except deletion.Blocked as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


async def _affiliate_names(db, merchant_id: str, ids) -> dict[str, str]:
    affs = await db.affiliates.find({"merchant_id": merchant_id, "_id": {"$in": list(set(ids))}}, {"user_id": 1}).to_list(None)
    users = {u["_id"]: u["name"] async for u in db.users.find({"_id": {"$in": [a["user_id"] for a in affs]}}, {"name": 1})}
    return {a["_id"]: users.get(a["user_id"], "") for a in affs}


# ---------- rewards (campaigns whose reward isn't cash) ----------


@router.get("/rewards")
async def list_rewards(
    status: Literal["earned", "fulfilled", "void"] | None = None,
    recipient: Literal["affiliate", "customer"] | None = None,
    affiliate_id: str | None = Query(None, max_length=64),
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1, le=10_000),
    m=Depends(current_merchant),
    db=Depends(db_dep),
):
    query: dict = {"merchant_id": m["_id"]}
    if status:
        query["status"] = status
    if recipient:
        query["recipient"] = recipient
    if affiliate_id:
        query["affiliate_id"] = affiliate_id
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        refs = [r["_id"] async for r in db.referrals.find({"merchant_id": m["_id"], "$or": [{"email": rx}, {"external_user_id": rx}, {"stripe_customer_id": rx}]}, {"_id": 1})]
        query["$or"] = [{"description": rx}, {"referral_id": {"$in": refs}}, {"affiliate_id": {"$in": await _matching_affiliates(db, m["_id"], rx)}}]
    rows, total = await _page(db.rewards, query, page)
    names = await _affiliate_names(db, m["_id"], [w["affiliate_id"] for w in rows])
    emails = {r["_id"]: r.get("email") async for r in db.referrals.find({"_id": {"$in": [w["referral_id"] for w in rows]}}, {"email": 1})}
    counts = {row["_id"]: row["n"] async for row in await db.rewards.aggregate([{"$match": {"merchant_id": m["_id"]}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    return {
        "items": [{**out(w), "affiliate_name": names.get(w["affiliate_id"], ""), "customer_email": emails.get(w["referral_id"])} for w in rows],
        "total": total, "page": page, "page_size": PAGE_SIZE, "counts": counts,
    }


class FulfillIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


@router.post("/rewards/{reward_id}/fulfill")
async def fulfill_reward(reward_id: str, body: FulfillIn | None = None, m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep)):
    try:
        r = await rewards.fulfill(db, m["_id"], reward_id, body.note if body else None, by=user["_id"])
    except rewards.RewardError as e:
        raise HTTPException(e.status, str(e))
    await audit.record(db, m["_id"], "reward.fulfilled", reward_id, note=r.get("note"))
    return out(r)


@router.post("/rewards/{reward_id}/unfulfill")
async def unfulfill_reward(reward_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    try:
        r = await rewards.unfulfill(db, m["_id"], reward_id)
    except rewards.RewardError as e:
        raise HTTPException(e.status, str(e))
    await audit.record(db, m["_id"], "reward.unfulfilled", reward_id)
    return out(r)


@router.get("/commissions")
async def list_commissions(
    status: Literal["pending", "paid", "void"] | None = None,
    affiliate_id: str | None = Query(None, max_length=64),
    # Unpaid commissions only: True = payable now (hold over, not held for review), False = not yet.
    due: bool | None = None,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1, le=10_000),
    m=Depends(current_merchant),
    db=Depends(db_dep),
):
    query: dict = {"merchant_id": m["_id"]}
    if status:
        query["status"] = status
    if affiliate_id:
        query["affiliate_id"] = affiliate_id
    if due is not None:
        now = datetime.now(UTC)
        query["status"] = "pending"
        query["$and"] = [{"due_at": {"$lte": now}, "held": {"$ne": True}} if due else {"$or": [{"due_at": {"$gt": now}}, {"held": True}]}]
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        refs = [x["_id"] async for x in db.referrals.find({"merchant_id": m["_id"], "$or": [{"email": rx}, {"stripe_customer_id": rx}, {"external_user_id": rx}]}, {"_id": 1}).limit(1000)]
        query["$or"] = [{"source_key": rx}, {"referral_id": {"$in": refs}}, {"affiliate_id": {"$in": await _matching_affiliates(db, m["_id"], rx)}}]
    rows, total = await _page(db.commissions, query, page)
    names = await _affiliate_names(db, m["_id"], [c["affiliate_id"] for c in rows])
    emails = {x["_id"]: x.get("email") async for x in db.referrals.find({"_id": {"$in": [c["referral_id"] for c in rows if c.get("referral_id")]}}, {"email": 1})}
    items = [{**out(c), "affiliate_name": names.get(c["affiliate_id"], ""), "customer": emails.get(c.get("referral_id"))} for c in rows]
    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE}


@router.get("/overview")
async def overview(m=Depends(current_merchant), db=Depends(db_dep)):
    mid = m["_id"]
    by_status: dict[str, dict[str, int]] = {}
    async for row in await db.commissions.aggregate([{"$match": {"merchant_id": mid, "status": {"$ne": "void"}}}, {"$group": {"_id": {"s": "$status", "c": "$currency"}, "t": {"$sum": "$amount_cents"}}}]):
        by_status.setdefault(row["_id"]["s"], {})[row["_id"]["c"]] = row["t"]
    revenue: dict[str, int] = {}
    async for row in await db.commissions.aggregate([{"$match": {"merchant_id": mid, "status": {"$ne": "void"}, "base_cents": {"$gt": 0}}}, {"$group": {"_id": "$currency", "t": {"$sum": "$base_cents"}}}]):
        revenue[row["_id"]] = row["t"]
    return {
        "affiliates": await db.affiliates.count_documents({"merchant_id": mid, "status": "approved"}),
        "pending_affiliates": await db.affiliates.count_documents({"merchant_id": mid, "status": "pending"}),
        "clicks": await db.clicks.count_documents({"merchant_id": mid, "test": False}),
        "leads": await db.referrals.count_documents({"merchant_id": mid, "test": {"$ne": True}}),
        # Signups that came from a tracked click: the only ones a click-to-signup rate can compare.
        # Imported referrals, codes and server-side signups have no click.
        "leads_from_clicks": await db.referrals.count_documents({"merchant_id": mid, "test": {"$ne": True}, "click_id": {"$type": "string"}}),
        "imported_leads": await db.referrals.count_documents({"merchant_id": mid, "test": {"$ne": True}, "source": "rewardful"}),
        "customers": await db.referrals.count_documents({"merchant_id": mid, "status": "customer", "test": {"$ne": True}}),
        "flagged": await db.referrals.count_documents({"merchant_id": mid, "test": {"$ne": True}, "flags.0": {"$exists": True}, "flags_cleared": {"$ne": True}}),
        "referred_revenue": revenue,
        "commissions": by_status,
        "stripe_connected": bool(m.get("stripe")),
        "installed": await db.clicks.count_documents({"merchant_id": mid}) > 0,
        "plan": plan_summary(m),
        "fx": await display_fx(db, m),
    }


async def display_fx(db, m: dict) -> dict | None:
    return await fx.for_display(db, (m["settings"].get("display_currency") or "usd"))


@router.get("/fx")
async def exchange_rates(m=Depends(current_merchant), db=Depends(db_dep)):
    """Today's rates into the program's display currency, for approximate totals. Null when unavailable."""
    return await display_fx(db, m)


@router.get("/audit")
async def audit_log(target: str | None = None, m=Depends(current_merchant), db=Depends(db_dep)):
    """Who approved, rejected, cleared, voided or paid what, newest first."""
    q = {"merchant_id": m["_id"]} | ({"target": target} if target else {})
    return [out(r) for r in await db.audit_log.find(q).sort("created_at", -1).limit(500).to_list(None)]


# ---------- payouts ----------


@router.get("/payouts")
async def list_payouts(m=Depends(current_merchant), db=Depends(db_dep)):
    history = await db.payouts.find({"merchant_id": m["_id"]}).sort("created_at", -1).limit(100).to_list(None)
    return {"payable": await payout_svc.payable(db, m["_id"]), "upcoming": await payout_svc.upcoming(db, m["_id"]), "history": [out(p) for p in history], "fee_bps": get_settings().payout_fee_bps, "paypal_connected": bool(m.get("paypal")), "stripe_payouts": get_settings().stripe_payouts}


class PayoutIn(BaseModel):
    currency: str
    method: Literal["stripe", "manual", "paypal"]
    # Manual only: pay just these affiliates (default: everyone payable in the currency).
    affiliate_ids: list[str] | None = None
    reference: str = Field(default="", max_length=200)


@router.post("/payouts")
async def create_payout(body: PayoutIn, m=Depends(current_merchant), db=Depends(db_dep), paypal=Depends(paypal_factory)):
    if body.method == "stripe":
        plans.require(m, "stripe_payouts")
    platform = platform_api() if body.method == "stripe" else None
    if body.method == "paypal" and not m.get("paypal"):
        raise HTTPException(400, "connect PayPal first")
    try:
        payout = await payout_svc.create_payout(
            db, m, body.currency.lower(), body.method, platform, body.affiliate_ids if body.method != "stripe" else None, body.reference,
            paypal(m) if body.method == "paypal" else None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.warning("payout failed for %s: %s", m["_id"], e)
        raise HTTPException(502, f"{body.method} rejected the payout: {e}")
    return out(payout)


class PayCommissionsIn(BaseModel):
    commission_ids: list[str] = Field(min_length=1, max_length=1000)
    reference: str = Field(default="", max_length=200)


@router.post("/payouts/commissions")
async def pay_chosen_commissions(body: PayCommissionsIn, m=Depends(current_merchant), db=Depends(db_dep)):
    """Mark chosen commissions paid, due or not: you paid the affiliate yourself."""
    try:
        payouts = await payout_svc.pay_commissions(db, m, body.commission_ids, body.reference)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return [out(p) for p in payouts]


@router.post("/payouts/{payout_id}/sync")
async def sync_payout(payout_id: str, m=Depends(current_merchant), db=Depends(db_dep), paypal=Depends(paypal_factory)):
    payout = await db.payouts.find_one({"_id": payout_id, "merchant_id": m["_id"], "method": "paypal", "status": "processing"})
    if not payout:
        raise HTTPException(400, "only PayPal payouts that are still processing can be refreshed")
    try:
        status = await payout_svc.sync_paypal_payout(db, payout, paypal(m))
    except Exception as e:
        raise HTTPException(502, f"PayPal: {e}")
    return {"status": status}


@router.get("/payouts/paypal.csv")
async def paypal_due_csv(currency: str | None = None, m=Depends(current_merchant), db=Depends(db_dep)):
    lines = [l for l in await payout_svc.payable(db, m["_id"]) if (not currency or l["currency"] == currency.lower()) and not l["needs_tax_form"]]
    return Response(payout_svc.paypal_csv(lines, f"{m['name']} affiliate commissions"), media_type="text/csv", headers={"content-disposition": 'attachment; filename="kickrail-paypal-payouts.csv"'})


class PayPalIn(BaseModel):
    client_id: str = Field(min_length=10, max_length=200)
    secret: str = Field(min_length=10, max_length=200)
    mode: Literal["sandbox", "live"] = "sandbox"


@router.put("/paypal")
async def connect_paypal(body: PayPalIn, m=Depends(current_merchant), db=Depends(db_dep), make=Depends(paypal_key_client)):
    try:
        await make(body.client_id.strip(), body.secret.strip(), body.mode).verify()
    except Exception as e:
        raise HTTPException(400, str(e))
    paypal = {"client_id": body.client_id.strip(), "secret_enc": encrypt(body.secret.strip()), "mode": body.mode, "connected_at": datetime.now(UTC)}
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"paypal": paypal}})
    await audit.record(db, m["_id"], "paypal.connected", m["_id"], client_id=paypal["client_id"], mode=body.mode)
    return merchant_out({**m, "paypal": paypal})


@router.delete("/paypal")
async def disconnect_paypal(m=Depends(current_merchant), db=Depends(db_dep)):
    await db.merchants.update_one({"_id": m["_id"]}, {"$unset": {"paypal": ""}})
    await audit.record(db, m["_id"], "paypal.disconnected", m["_id"])
    return {"ok": True}


@router.get("/payouts/due.csv")
async def due_csv(currency: str | None = None, m=Depends(current_merchant), db=Depends(db_dep)):
    lines = [l for l in await payout_svc.payable(db, m["_id"]) if not currency or l["currency"] == currency.lower()]
    return Response(payout_svc.due_csv(lines), media_type="text/csv", headers={"content-disposition": 'attachment; filename="kickrail-due.csv"'})


# ---------- tax forms ----------


@router.get("/tax")
async def tax_forms(m=Depends(current_merchant), db=Depends(db_dep)):
    year = datetime.now(UTC).year
    paid = await _paid_by_affiliate(db, m["_id"], year)
    # Affiliates on a campaign whose reward isn't cash are never paid, so they never need a
    # tax form, and a customer-referral program can have one per customer. They stay listed
    # if they were paid this year.
    custom = [c["_id"] async for c in db.campaigns.find({"merchant_id": m["_id"], "reward.type": "custom"}, {"_id": 1})]
    affs = await db.affiliates.find({"merchant_id": m["_id"], "status": {"$ne": "rejected"}, "$or": [{"campaign_id": {"$nin": custom}}, {"_id": {"$in": list(paid)}}]}).to_list(None)
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [a["user_id"] for a in affs]}})}
    rows = []
    for a in affs:
        u = users.get(a["user_id"], {})
        t = u.get("tax_info")
        rows.append(
            {
                "affiliate_id": a["_id"],
                "name": u.get("name", ""),
                "email": u.get("email", ""),
                "form": t and t["form"],
                "legal_name": t and t["legal_name"],
                "country": t and t["country"],
                "tin_last4": t and t["tin_last4"],
                "signed_at": t and t["signed_at"],
                "paid_this_year": paid.get(a["_id"], {}),
            }
        )
    return {"year": year, "require_tax_form": m["settings"].get("require_tax_form", False), "affiliates": rows}


async def _paid_by_affiliate(db, merchant_id: str, year: int) -> dict[str, dict[str, int]]:
    start, end = datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)
    out_: dict[str, dict[str, int]] = {}
    async for row in await db.commissions.aggregate(
        [{"$match": {"merchant_id": merchant_id, "status": "paid", "paid_at": {"$gte": start, "$lt": end}}}, {"$group": {"_id": {"a": "$affiliate_id", "c": "$currency"}, "t": {"$sum": "$amount_cents"}}}]
    ):
        out_.setdefault(row["_id"]["a"], {})[row["_id"]["c"]] = row["t"]
    return out_


@router.get("/tax/1099.csv")
async def tax_1099(year: int, m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep)):
    """US affiliates (W-9) paid 600 USD or more in the year: the 1099-NEC list.
    Includes full TINs, so only the workspace owner can download it."""
    if user["_id"] != m.get("owner_id"):
        raise HTTPException(403, "only the workspace owner can download TINs")
    import csv
    import io

    paid = await _paid_by_affiliate(db, m["_id"], year)
    affs = {a["_id"]: a async for a in db.affiliates.find({"merchant_id": m["_id"], "_id": {"$in": list(paid)}})}
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [a["user_id"] for a in affs.values()]}})}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["legal_name", "business_name", "tin", "address", "email", "box1_nonemployee_compensation_usd", "affiliate_id"])
    for aff_id, by_cur in paid.items():
        u = users.get(affs.get(aff_id, {}).get("user_id"), {})
        t = u.get("tax_info") or {}
        usd = by_cur.get("usd", 0)
        if t.get("form") == "w9" and usd >= 60_000:
            w.writerow([t["legal_name"], t.get("business_name", ""), decrypt(t["tin_enc"]), t["address"], u.get("email", ""), f"{usd / 100:.2f}", aff_id])
    log.info("1099 export for %s %s by %s", m["_id"], year, user["_id"])
    return Response(buf.getvalue(), media_type="text/csv", headers={"content-disposition": f'attachment; filename="kickrail-1099-{year}.csv"'})


@router.post("/payouts/{payout_id}/undo")
async def undo_payout(payout_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    if not await payout_svc.undo_manual_payout(db, m["_id"], payout_id):
        raise HTTPException(400, "only manual payouts marked paid can be undone")
    return {"ok": True}


@router.post("/payouts/{payout_id}/cancel")
async def cancel_payout(payout_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    if not await payout_svc.cancel_payout(db, m["_id"], payout_id):
        raise HTTPException(400, "only unfunded payouts can be cancelled")
    return {"ok": True}


@router.get("/payouts/{payout_id}/csv")
async def payout_csv(payout_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    payout = await db.payouts.find_one({"_id": payout_id, "merchant_id": m["_id"]})
    if not payout:
        raise HTTPException(404, "payout not found")
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [i["user_id"] for i in payout["items"]]}})}
    return Response(payout_svc.payout_csv(payout, users), media_type="text/csv", headers={"content-disposition": f'attachment; filename="{payout_id}.csv"'})




# ---------- moving in and out ----------


@router.get("/export/{kind}.csv")
async def export_csv(kind: str, m=Depends(current_merchant), db=Depends(db_dep)):
    if kind not in EXPORTS:
        raise HTTPException(404, "unknown export")
    name = f"{m['slug']}-{kind}-{datetime.now(UTC):%Y-%m-%d}.csv"
    return StreamingResponse(EXPORTS[kind](db, m), media_type="text/csv", headers={"content-disposition": f'attachment; filename="{name}"'})


class RewardfulImportIn(BaseModel):
    # Used for this run only: never stored, logged or sent back.
    api_secret: str = Field(min_length=10, max_length=200)
    send_claim_emails: bool = False
    # Emails or Rewardful affiliate ids. Empty imports the whole program.
    only: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=100)


# Running imports, so the event loop doesn't drop them before they finish.
_imports: set[asyncio.Task] = set()


@router.get("/import")
async def latest_import(m=Depends(current_merchant), db=Depends(db_dep)):
    return {"import": rewardful_import.import_out(await db.imports.find_one({"merchant_id": m["_id"]}, sort=[("started_at", -1)]))}


@router.post("/import/rewardful")
async def import_rewardful(body: RewardfulImportIn, m=Depends(current_merchant), user=Depends(current_user), db=Depends(db_dep), client=Depends(rewardful_client)):
    if await rewardful_import.running_import(db, m["_id"]):
        raise HTTPException(409, "an import is already running")
    api = client(body.api_secret.strip())
    try:
        await api.get("/campaigns", [("limit", 1)])
    except rewardful_import.RewardfulError as e:
        await api.__aexit__(None, None, None)
        raise HTTPException(400, str(e))
    only = rewardful_import.clean_only(body.only)
    doc = await rewardful_import.start(db, m, user["_id"], body.send_claim_emails, only)
    task = asyncio.create_task(rewardful_import.run_import(db, m, doc["_id"], api, body.send_claim_emails, only))
    _imports.add(task)
    task.add_done_callback(_imports.discard)
    return {"import": rewardful_import.import_out(doc)}
