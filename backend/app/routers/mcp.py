"""Kickrail as an MCP server, so a coding agent can set a program up from the
merchant's own repo: install the script, set commissions, check it all works.

Streamable HTTP, stateless: every request is one JSON-RPC message (or a batch)
answered with plain JSON. Authenticated with the program's secret key
(Authorization: Bearer sk_kr_...), the same key as the server API.
"""

import asyncio
import ipaddress
import json
import socket
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, EmailStr, Field, ValidationError

from .. import deps, plans
from ..config import get_settings
from ..ids import sha256
from ..security import db_dep
from ..services import audit
from ..serializers import affiliate_url, join_url, portal_base
from . import merchant as mr
from . import server_api as api

router = APIRouter(tags=["mcp"])

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = """Kickrail runs a Stripe affiliate program. Setting one up, in order:
1. setup_status: see what's done and what's next. Call it first and after each step.
2. connect_stripe: Kickrail needs to see payments. Give the user the link; only they can approve on Stripe.
3. get_install_instructions, then add the tracking script to the user's site and app in their codebase.
4. verify_install: checks the live site for the script and gives a test link.
5. Review the commission (list_campaigns, update_campaign or create_campaign).
6. Invite affiliates: share the join page from setup_status, or add_affiliate.
Optional: serve the join page from the user's own subdomain with add_portal_domain, then check_portal_domain.
Moving from Rewardful: start_rewardful_import. Amounts are in cents (5000 = 50.00)."""


# ---------- tool inputs ----------


class NoArgs(BaseModel):
    pass


class InstallArgs(BaseModel):
    framework: Literal["nextjs-app", "nextjs-pages", "react-spa", "html", "wordpress", "webflow", "framer", "shopify", "other"] = Field(
        default="other", description="what the marketing site and app are built with"
    )


class VerifyArgs(BaseModel):
    url: str | None = Field(default=None, description="a page on the program's website to check; defaults to the website's home page")


class CampaignArgs(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    rule_type: Literal["percent", "flat"] = Field(description="percent of each payment, or a flat amount per payment")
    percent: float | None = Field(default=None, gt=0, le=100, description="for percent, e.g. 30")
    flat_cents: int | None = Field(default=None, gt=0, description="for flat, in cents")
    currency: str = "usd"
    duration_mode: Literal["once", "months", "forever"] = Field(description="once = first payment only; months = recurring for `months`; forever = every payment")
    months: int | None = Field(default=None, ge=1, le=120)
    hold_days: int = Field(default=30, ge=0, le=180, description="refund window before a commission can be paid")
    min_payout_cents: int = Field(default=5000, ge=0, description="smallest balance worth paying out")
    lead_bounty_cents: int = Field(default=0, ge=0, le=1_000_000, description="optional flat amount per signup, before any payment")
    public: bool = Field(default=False, description="public campaigns get their own join page")
    slug: str | None = Field(default=None, max_length=40, description="the join page name for a public campaign")
    landing_url: str | None = Field(default=None, max_length=1000, description="where this campaign's links point, on the program's website")
    stripe_coupon_id: str | None = Field(default=None, description="a Stripe coupon that affiliate codes give customers")


class CampaignUpdate(BaseModel):
    campaign_id: str
    name: str | None = Field(default=None, min_length=1, max_length=60)
    rule_type: Literal["percent", "flat"] | None = None
    percent: float | None = Field(default=None, gt=0, le=100)
    flat_cents: int | None = Field(default=None, gt=0)
    currency: str | None = None
    duration_mode: Literal["once", "months", "forever"] | None = None
    months: int | None = Field(default=None, ge=1, le=120)
    hold_days: int | None = Field(default=None, ge=0, le=180)
    min_payout_cents: int | None = Field(default=None, ge=0)
    lead_bounty_cents: int | None = Field(default=None, ge=0, le=1_000_000)
    public: bool | None = None
    slug: str | None = Field(default=None, max_length=40)
    landing_url: str | None = Field(default=None, max_length=1000)
    stripe_coupon_id: str | None = None
    make_default: bool = Field(default=False, description="new affiliates join the default campaign")


class ProgramUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    website: str | None = Field(default=None, description="the site affiliate links point to, e.g. https://example.com")
    cookie_days: int | None = Field(default=None, ge=1, le=365, description="how long a click counts")
    param_names: list[str] | None = Field(default=None, min_length=1, max_length=5, description="URL parameters the script reads, e.g. ['via', 'ref']")
    auto_approve: bool | None = Field(default=None, description="approve people who join without review")
    attribution: Literal["first", "last"] | None = Field(default=None, description="first: the first affiliate to refer someone keeps them. last: a newer click, link or code moves them, until their first payment")


class AffiliateArgs(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    send_welcome_email: bool = Field(description="email them their link now; false for test affiliates")
    campaign_id: str | None = None
    token: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{3,32}$", description="the link value (?via=token); made from the name if omitted")
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{3,20}$", description="creator code, if the campaign has a Stripe coupon")
    status: Literal["pending", "approved"] = "approved"


class ListArgs(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    starting_after: str | None = Field(default=None, description="the last id from the previous page")
    status: str | None = None


class DomainArgs(BaseModel):
    host: str = Field(max_length=253, description="a subdomain the user owns, e.g. partners.example.com (a root domain can't be a CNAME)")


class ImportArgs(BaseModel):
    api_secret: str = Field(min_length=10, max_length=200, description="the Rewardful API secret, from Rewardful > Company settings. Used for this import only, never stored.")
    send_claim_emails: bool = Field(default=False, description="email each affiliate a link to set a Kickrail password")
    only: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=100, description="import only these affiliates, by email or Rewardful affiliate id, with their campaigns, referrals, commissions and payouts. Empty imports the whole program.")


# ---------- helpers ----------


def _dep(request: Request, dep):
    """A dependency's value, honouring test overrides."""
    return request.app.dependency_overrides.get(dep, dep)()


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=UTC) if d and d.tzinfo is None else d


def _iso(d: datetime | None) -> str | None:
    return _aware(d).isoformat() if d else None


async def _blocked(host: str) -> bool:
    """True when the host resolves to somewhere private (loopback, LAN, metadata)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return True
    return False


async def fetch_page(m: dict, url: str) -> tuple[str, str]:
    """GET a page on the program's own website. Returns (final url, html)."""
    site = (urlsplit(m["website"]).hostname or "").removeprefix("www.")
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, headers={"user-agent": "Kickrail install check"}) as http:
        for _ in range(4):
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            if parts.scheme not in ("http", "https") or not host or not (host.removeprefix("www.") == site or host.endswith(f".{site}")):
                raise ValueError(f"can only check pages on {site}")
            if await _blocked(host):
                raise ValueError(f"{host} doesn't resolve to a public address")
            r = await http.get(url)
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            return url, r.text[:2_000_000]
    raise ValueError("too many redirects")


def _script_on_page(m: dict, html: str) -> bool:
    return m["public_key"] in html and "kr.js" in html


async def _test_link(db, m: dict) -> str | None:
    aff = await db.affiliates.find_one({"merchant_id": m["_id"], "status": "approved"}, sort=[("created_at", 1)])
    return f"{affiliate_url(m, aff['token'])}&kr_test=1" if aff else None


def _connect_url(m: dict) -> str:
    return f"{get_settings().public_url}/dashboard/stripe/connect?program={m['_id']}"


# ---------- tools ----------


async def setup_status(request: Request, db, m: dict, _: NoArgs) -> dict:
    tracking = m.get("tracking") or {}
    affiliates = await db.affiliates.count_documents({"merchant_id": m["_id"]})
    test_clicks = await db.clicks.count_documents({"merchant_id": m["_id"], "test": True})
    clicks = await db.clicks.count_documents({"merchant_id": m["_id"], "test": {"$ne": True}})
    referrals = await db.referrals.count_documents({"merchant_id": m["_id"]})
    campaign = await db.campaigns.find_one({"merchant_id": m["_id"], "is_default": True})
    base = get_settings().public_url
    stripe = m.get("stripe")
    steps = [
        {"step": "connect_stripe", "done": bool(stripe), "how": "call connect_stripe and give the user the link"},
        {"step": "install_script", "done": bool(tracking.get("script_seen_at")), "how": "get_install_instructions, add it to the site and app, deploy, then verify_install"},
        {"step": "test_referral", "done": bool(test_clicks or clicks), "how": "open the test link from verify_install in a browser, then sign up with a test email"},
        {"step": "invite_affiliates", "done": affiliates > 0, "how": "share the join page, or add_affiliate"},
    ]
    return {
        "program": {"id": m["_id"], "name": m["name"], "website": m["website"], "plan": plans.current(m)["name"], "plan_status": plans.current(m)["status"]},
        "stripe": {"connected": bool(stripe), "account_name": (stripe or {}).get("account_name"), "livemode": (stripe or {}).get("livemode")},
        "script": {"last_loaded_at": _iso(tracking.get("script_seen_at")), "last_loaded_on": tracking.get("script_seen_on")},
        "counts": {"affiliates": affiliates, "clicks": clicks, "test_clicks": test_clicks, "referrals": referrals},
        "default_campaign": mr.campaign_out(campaign, m)["description"] if campaign else None,
        "join_page": join_url(m),
        "portal_domains": [{"host": d["host"], "status": mr.domain_out(d)["status"], "primary": bool(d.get("primary"))} for d in m.get("portal_domains") or []],
        "affiliate_portal": portal_base(m),
        "dashboard": f"{base}/dashboard",
        "next_step": next((s["step"] for s in steps if not s["done"]), None),
        "steps": steps,
    }


INSTALL_WHERE = {
    "nextjs-app": "app/layout.tsx: import Script from 'next/script' and render <Script src=\"{src}\" strategy=\"afterInteractive\" /> inside <body>. If the marketing site and the app are separate projects, add it to both.",
    "nextjs-pages": "pages/_app.tsx (or _document.tsx): render <Script src=\"{src}\" strategy=\"afterInteractive\" /> from 'next/script'.",
    "react-spa": "index.html: put the tag in <head>. The script survives client-side navigation, so once per page load is enough.",
    "html": "Every page's <head>, or the shared header include/template.",
    "wordpress": "Appearance > Theme file editor > header.php before </head>, or a header-scripts plugin. Use the HTML tag as is.",
    "webflow": "Site settings > Custom code > Head code, then publish.",
    "framer": "Site settings > General > Custom code > End of <head>, then publish.",
    "shopify": "Online Store > Themes > Edit code > layout/theme.liquid before </head>.",
    "other": "The <head> of every page of the marketing site and the app, so a visitor who lands on any page is tracked.",
}


async def get_install_instructions(request: Request, db, m: dict, a: InstallArgs) -> dict:
    base = get_settings().public_url
    src = f"{base}/api/kr.js?k={m['public_key']}"
    param = m["settings"]["param_names"][0]
    return {
        "script_tag": mr.snippet(m),
        "where": INSTALL_WHERE[a.framework].format(src=src),
        "what_it_does": f"Reads ?{param}=<affiliate> from the URL, stores the click in a first-party cookie for {m['settings']['cookie_days']} days, and when the visitor submits a form with an email in it (a signup form), records them as a referral. Their first Stripe payment then earns the commission. Stripe Payment Links, pricing tables and buy buttons get the referral too.",
        "signup_forms": "Plain HTML forms with an email field work with no changes. Forms submitted with fetch/JS (React state, server actions) may not be seen; for those, report the signup from the server (below), which is also the most reliable way overall. Add data-kickrail-ignore to a form that should not count (newsletter, contact).",
        "server_side_signup": {
            "why": "Server to server, so ad blockers and Safari cookie limits never get a say. Recommended for apps with a signup endpoint.",
            "browser": "window.Kickrail.referral holds the click id (also in the kr_ref cookie). Send it with the signup request.",
            "request": f"POST {base}/api/v1/referrals with Authorization: Bearer <the same sk_kr_ key this MCP uses, from an env var such as KICKRAIL_SECRET_KEY> and JSON {{\"referral\": <kr_ref cookie>, \"email\": <user email>, \"user_id\": <your user id>, \"stripe_customer_id\": <cus_... if you have one>}}. Never put the key in browser code.",
            "fail_open": "Don't block signup on this call: catch errors and move on.",
        },
        "first_party_proxy": "Optional, to dodge ad blockers: proxy /kr/* on the site to " + f"{base}/api/* and load the script as /kr/kr.js?k={m['public_key']}&api=/kr",
        "after_deploying": "Call verify_install.",
    }


async def connect_stripe(request: Request, db, m: dict, _: NoArgs) -> dict:
    stripe = m.get("stripe")
    if stripe:
        return {"connected": True, "account_name": stripe.get("account_name"), "livemode": stripe.get("livemode"), "note": "Already connected. To switch accounts, use Settings in the dashboard."}
    if not get_settings().stripe_oauth:
        return {"connected": False, "url": f"{get_settings().public_url}/dashboard/settings#stripe", "tell_the_user": "Open this link and connect Stripe with a restricted key, following the steps on the page."}
    return {
        "connected": False,
        "url": _connect_url(m),
        "tell_the_user": "Open this link, sign in to Kickrail if asked, and approve Kickrail on Stripe. Only you can do this step. Tell me when it's done.",
        "then": "call setup_status to confirm stripe.connected",
    }


async def verify_install(request: Request, db, m: dict, a: VerifyArgs) -> dict:
    url = a.url or f"{m['website']}/"
    out: dict = {"checked_url": url}
    try:
        final, html = await fetch_page(m, url)
        out["checked_url"] = final
        out["script_in_page_html"] = _script_on_page(m, html)
    except (ValueError, httpx.HTTPError) as e:
        out["script_in_page_html"] = None
        out["fetch_error"] = str(e) or type(e).__name__
    tracking = m.get("tracking") or {}
    seen = _aware(tracking.get("script_seen_at"))
    out["script_last_loaded_at"] = _iso(seen)
    out["script_last_loaded_on"] = tracking.get("script_seen_on")
    since = datetime.now(UTC) - timedelta(hours=24)
    out["test_clicks_last_24h"] = await db.clicks.count_documents({"merchant_id": m["_id"], "test": True, "created_at": {"$gte": since}})
    out["referrals_last_24h"] = await db.referrals.count_documents({"merchant_id": m["_id"], "created_at": {"$gte": since}})
    link = await _test_link(db, m)
    if link:
        out["test_link"] = link
        out["how_to_test"] = "Open test_link in a real browser (the script runs client-side, so fetching it won't count), then call verify_install again: test_clicks_last_24h should go up. Signing up on the site with a test email after that click should add a referral."
    else:
        out["how_to_test"] = "There's no approved affiliate yet. Add one for yourself with add_affiliate (send_welcome_email false), then call verify_install again for a test link."
    if out["script_in_page_html"] is False and not seen:
        out["diagnosis"] = "The script isn't in the page HTML and has never loaded. Add it (get_install_instructions) and deploy."
    elif out["script_in_page_html"] is False and seen:
        out["diagnosis"] = "Not in the server HTML, but it has loaded in browsers, so it's probably added client-side. That works."
    elif seen:
        out["diagnosis"] = "Installed: the script has loaded on a live page."
    else:
        out["diagnosis"] = "The tag is in the page but no browser has loaded it yet. Open the site once in a browser."
    return out


async def list_campaigns(request: Request, db, m: dict, _: NoArgs) -> dict:
    return {"campaigns": await mr.list_campaigns(m=m, db=db)}


def _campaign_in(fields: dict) -> mr.CampaignIn:
    try:
        return mr.CampaignIn(**fields)
    except ValidationError as e:
        raise HTTPException(422, _validation(e))


async def create_campaign(request: Request, db, m: dict, a: CampaignArgs) -> dict:
    return await mr.create_campaign(_campaign_in(a.model_dump()), m=m, db=db)


def _campaign_fields(c: dict) -> dict:
    """An existing campaign back into CampaignIn fields, so updates can be partial."""
    rule, duration = c["rule"], c["duration"]
    bounty = c.get("lead_bounty") or {}
    return {
        "name": c["name"],
        "rule_type": rule["type"],
        "percent": rule["bps"] / 100 if rule["type"] == "percent" else None,
        "flat_cents": rule.get("cents"),
        "currency": rule.get("currency", "usd"),
        "duration_mode": duration["mode"],
        "months": duration.get("months"),
        "hold_days": c["hold_days"],
        "min_payout_cents": c["min_payout_cents"],
        "stripe_coupon_id": c.get("stripe_coupon_id"),
        "lead_bounty_cents": bounty.get("cents", 0),
        "lead_bounty_currency": bounty.get("currency", "usd"),
        "product_rules": [
            {"match": r["match"], "id": r["id"], "label": r.get("label", ""), "rule": {"type": r["rule"]["type"], "percent": r["rule"].get("bps", 0) / 100 or None, "flat_cents": r["rule"].get("cents"), "currency": r["rule"].get("currency", "usd")}}
            for r in c.get("product_rules") or []
        ],
        "public": bool(c.get("public")),
        "slug": c.get("slug"),
        "landing_url": c.get("landing_url"),
    }


async def update_campaign(request: Request, db, m: dict, a: CampaignUpdate) -> dict:
    c = await db.campaigns.find_one({"_id": a.campaign_id, "merchant_id": m["_id"]})
    if not c:
        raise HTTPException(404, "campaign not found")
    changes = a.model_dump(exclude_unset=True, exclude={"campaign_id", "make_default"})
    fields = _campaign_fields(c) | changes
    if changes.get("rule_type") == "percent":
        fields["flat_cents"] = None
    if changes.get("duration_mode") in ("once", "forever"):
        fields["months"] = None
    out = await mr.update_campaign(a.campaign_id, _campaign_in(fields), m=m, db=db, factory=_dep(request, deps.merchant_api_factory))
    if a.make_default:
        await mr.make_default(a.campaign_id, m=m, db=db)
        out["is_default"] = True
    return out


async def update_program(request: Request, db, m: dict, a: ProgramUpdate) -> dict:
    try:
        body = mr.SettingsIn(**a.model_dump(exclude_none=True))
    except ValidationError as e:
        raise HTTPException(422, _validation(e))
    out = await mr.update_merchant(body, m=m, db=db)
    return {k: out[k] for k in ("id", "name", "website", "settings", "join_url")} | {"script_tag": out["snippet"]}


async def add_affiliate(request: Request, db, m: dict, a: AffiliateArgs) -> dict:
    plans.require(m, "api")
    body = api.AffiliateCreate(**a.model_dump())
    return await api.create(body, m=m, db=db, factory=_dep(request, deps.merchant_api_factory))


async def list_affiliates(request: Request, db, m: dict, a: ListArgs) -> dict:
    plans.require(m, "api")
    if a.status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(422, "status is pending, approved or rejected")
    return await api.list_affiliates(limit=a.limit, starting_after=a.starting_after, status=a.status, email=None, campaign_id=None, m=m, db=db)


async def list_referrals(request: Request, db, m: dict, a: ListArgs) -> dict:
    plans.require(m, "api")
    if a.status not in (None, "lead", "customer"):
        raise HTTPException(422, "status is lead or customer")
    return await api.list_referrals(limit=a.limit, starting_after=a.starting_after, affiliate_id=None, status=a.status, m=m, db=db)


async def list_commissions(request: Request, db, m: dict, a: ListArgs) -> dict:
    plans.require(m, "api")
    if a.status not in (None, "pending", "paid", "void"):
        raise HTTPException(422, "status is pending, paid or void")
    return await api.list_commissions(limit=a.limit, starting_after=a.starting_after, affiliate_id=None, referral_id=None, status=a.status, m=m, db=db)


async def start_rewardful_import(request: Request, db, m: dict, a: ImportArgs) -> dict:
    owner = await db.users.find_one({"_id": m.get("owner_id")})
    if not owner:
        raise HTTPException(409, "the program has no owner account")
    body = mr.RewardfulImportIn(api_secret=a.api_secret, send_claim_emails=a.send_claim_emails, only=a.only)
    out = await mr.import_rewardful(body, m=m, user=owner, db=db, client=_dep(request, deps.rewardful_client))
    return out | {"then": "call import_status until status is done"}


async def import_status(request: Request, db, m: dict, _: NoArgs) -> dict:
    return await mr.latest_import(m=m, db=db)


DOMAIN_HOW = "At the DNS provider, add dns_record (a CNAME; on Cloudflare set it to DNS only, grey cloud), then call check_portal_domain. DNS can take a few minutes to an hour."


def _domain_reply(d: dict) -> dict:
    out = mr.domain_out(d)
    if out["status"] == "not_verified":
        out["next"] = DOMAIN_HOW
    elif out["status"] == "waiting_for_https":
        out["next"] = "DNS is verified and the certificate is being issued. Call check_portal_domain again in a minute."
    else:
        out["next"] = "Live. The join page, affiliate portal, links and emails use it" + (" (it's the primary domain)." if out["primary"] else " once it's made primary in Settings.")
    return out


async def list_portal_domains(request: Request, db, m: dict, _: NoArgs) -> dict:
    limit = plans.current(m)["domains"]
    return {"domains": [_domain_reply(d) for d in m.get("portal_domains") or []], "plan_allows": limit,
            "note": "No custom domain: the join page is on kickrail.com." if not m.get("portal_domains") else None}


async def add_portal_domain(request: Request, db, m: dict, a: DomainArgs) -> dict:
    return _domain_reply((await mr.add_domain(mr.DomainIn(host=a.host), m=m, db=db))["domain"])


async def check_portal_domain(request: Request, db, m: dict, a: DomainArgs) -> dict:
    return _domain_reply((await mr.verify_domain(a.host.strip().lower().removeprefix("https://").rstrip("/"), m=m, db=db))["domain"])


TOOLS: dict[str, tuple] = {
    # name: (handler, input model, description, read only)
    "setup_status": (setup_status, NoArgs, "What's set up in this Kickrail program and what to do next. Call first, and after each step.", True),
    "get_install_instructions": (get_install_instructions, InstallArgs, "The tracking script tag, where to put it for a given framework, and how to report signups from the server.", True),
    "connect_stripe": (connect_stripe, NoArgs, "A link the user opens to connect their Stripe account. Only the user can approve it on Stripe.", True),
    "verify_install": (verify_install, VerifyArgs, "Check the live website for the tracking script, see whether browsers have loaded it, and get a test link.", True),
    "list_campaigns": (list_campaigns, NoArgs, "Commission campaigns: rate, duration, hold, join page.", True),
    "create_campaign": (create_campaign, CampaignArgs, "Add a commission campaign, e.g. 30% recurring for 12 months.", False),
    "update_campaign": (update_campaign, CampaignUpdate, "Change a campaign. Only the fields you pass change. Affects future commissions only.", False),
    "update_program": (update_program, ProgramUpdate, "Change the program name, website, cookie length, URL parameters or auto-approval.", False),
    "add_affiliate": (add_affiliate, AffiliateArgs, "Add an affiliate by email. They get an account and a link. Growth plan or trial.", False),
    "list_affiliates": (list_affiliates, ListArgs, "Affiliates with links, codes and stats, newest first. status: pending, approved or rejected.", True),
    "list_referrals": (list_referrals, ListArgs, "People affiliates referred, newest first. status: lead or customer.", True),
    "list_commissions": (list_commissions, ListArgs, "Commissions, newest first. status: pending, paid or void. Amounts in cents.", True),
    "list_portal_domains": (list_portal_domains, NoArgs, "Custom domains for the join page and affiliate portal, with status (not_verified, waiting_for_https, live) and the DNS record each needs.", True),
    "add_portal_domain": (add_portal_domain, DomainArgs, "Serve the join page and affiliate portal from the user's own subdomain. Returns the CNAME record to create. Starter plan and up.", False),
    "check_portal_domain": (check_portal_domain, DomainArgs, "Check a portal domain's DNS and HTTPS, like the Check DNS button. Run it after the CNAME is added.", False),
    "start_rewardful_import": (start_rewardful_import, ImportArgs, "Copy campaigns, affiliates, links, codes, referrals and commissions from Rewardful, or only some affiliates' (only). Affiliates' existing links keep working.", False),
    "import_status": (import_status, NoArgs, "Progress of the latest Rewardful import.", True),
}


def _schema(model: type[BaseModel]) -> dict:
    s = model.model_json_schema()
    s.pop("title", None)
    for p in s.get("properties", {}).values():
        p.pop("title", None)
    return s | {"type": "object", "properties": s.get("properties", {})}


def tool_list() -> list[dict]:
    return [
        {"name": n, "description": d, "inputSchema": _schema(model), "annotations": {"readOnlyHint": ro, "openWorldHint": n in ("verify_install", "start_rewardful_import", "add_portal_domain", "check_portal_domain")}}
        for n, (_, model, d, ro) in TOOLS.items()
    ]


def _validation(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'input'}: {err['msg']}" for err in e.errors())


def _text(obj) -> str:
    return json.dumps(obj, default=lambda v: _iso(v) if isinstance(v, datetime) else str(v), indent=1)


async def call_tool(request: Request, db, m: dict, name: str, args: dict) -> dict:
    if name not in TOOLS:
        raise KeyError(name)
    handler, model, _, _ = TOOLS[name]
    try:
        result = await handler(request, db, m, model(**(args or {})))
    except ValidationError as e:
        return {"content": [{"type": "text", "text": f"Invalid arguments: {_validation(e)}"}], "isError": True}
    except HTTPException as e:
        return {"content": [{"type": "text", "text": str(e.detail)}], "isError": True}
    text = _text(result)
    return {"content": [{"type": "text", "text": text}], "structuredContent": json.loads(text)}


# ---------- transport ----------


def _err(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


async def handle(request: Request, db, m: dict, msg) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
    method, id_, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:
        return None  # notifications (initialized, cancelled) need no answer
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "kickrail", "title": "Kickrail", "version": "1.0.0"},
            "instructions": INSTRUCTIONS + f"\nThis key belongs to the program \"{m['name']}\" ({m['website']}).",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tool_list()}}
    if method == "tools/call":
        try:
            result = await call_tool(request, db, m, str(params.get("name")), params.get("arguments") or {})
        except KeyError:
            return _err(id_, -32602, f"unknown tool: {params.get('name')}")
        return {"jsonrpc": "2.0", "id": id_, "result": result}
    return _err(id_, -32601, f"method not found: {method}")


@router.post("/mcp")
async def mcp(request: Request):
    db = await db_dep()
    key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    m = await db.merchants.find_one({"secret_key_hash": sha256(key)}) if key.startswith("sk_kr_") else None
    if not m:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Send your program's secret key as Authorization: Bearer sk_kr_... (Kickrail > Settings > Server API key)."}},
            status_code=401,
        )
    audit.actor.set({"kind": "mcp"})
    try:
        body = json.loads(await request.body())
    except ValueError:
        return JSONResponse(_err(None, -32700, "parse error"), status_code=400)
    if isinstance(body, list):
        replies = [r for r in [await handle(request, db, m, x) for x in body] if r]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await handle(request, db, m, body)
    return JSONResponse(reply) if reply else Response(status_code=202)


@router.get("/mcp")
@router.delete("/mcp")
async def mcp_no_stream():
    # Stateless server: no server-initiated stream and no sessions to end.
    return Response(status_code=405, headers={"allow": "POST"})
