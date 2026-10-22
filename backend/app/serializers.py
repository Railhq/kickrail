"""Public object shapes. The same dicts go out in /v1 API responses and in webhook
payloads, so a merchant's code handles one format."""

from urllib.parse import urlsplit, urlunsplit

from .config import get_settings


def affiliate_url(m: dict, token: str, landing_url: str | None = None) -> str:
    param = m["settings"]["param_names"][0]
    base = landing_url or f"{m['website']}/"
    parts = urlsplit(base)
    query = f"{parts.query}&{param}={token}" if parts.query else f"{param}={token}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, parts.fragment))


def primary_domain(m: dict) -> dict | None:
    """The verified portal domain links and emails use: the one marked primary, else the oldest verified."""
    live = [d for d in m.get("portal_domains") or [] if d.get("verified")]
    return next((d for d in live if d.get("primary")), live[0] if live else None)


def portal_base(m: dict) -> str:
    """Where affiliates of this program sign in: the primary custom domain once it is verified."""
    d = primary_domain(m)
    if d:
        local = d["host"].endswith(".localhost")
        port = urlsplit(get_settings().public_url).port if local else None
        return f"{'http' if local else 'https'}://{d['host']}{f':{port}' if port else ''}"
    return get_settings().public_url


def join_url(m: dict, campaign: dict | None = None) -> str:
    """The program's join page, or a public campaign's own one."""
    if campaign and campaign.get("slug"):
        return f"{portal_base(m)}/join/{campaign['slug']}" if primary_domain(m) else f"{portal_base(m)}/join/{m['slug']}/{campaign['slug']}"
    return f"{portal_base(m)}/" if primary_domain(m) else f"{portal_base(m)}/join/{m['slug']}"


def link_obj(m: dict, link: dict) -> dict:
    return {"id": link["_id"], "token": link["token"], "url": affiliate_url(m, link["token"], link.get("landing_url")), "landing_url": link.get("landing_url"), "label": link.get("label", ""), "created_at": link["created_at"]}


def code_obj(c: dict) -> dict:
    return {"id": c["_id"], "code": c["code"], "redeemable_at_checkout": bool(c.get("stripe_promotion_code_id")), "created_at": c["created_at"]}


def affiliate_obj(m: dict, aff: dict, user: dict | None, links: list[dict] | None = None, codes: list[dict] | None = None, campaign: dict | None = None) -> dict:
    """campaign: the affiliate's, so the main link uses its landing page."""
    user = user or {}
    return {
        "id": aff["_id"],
        "object": "affiliate",
        "status": aff["status"],
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "campaign_id": aff["campaign_id"],
        "token": aff["token"],
        "link": affiliate_url(m, aff["token"], (campaign or {}).get("landing_url")),
        "code": aff.get("code"),
        "code_redeemable_at_checkout": bool(aff.get("stripe_promotion_code_id")) and aff.get("stripe_promotion_code") == aff.get("code"),
        "links": [link_obj(m, l) for l in links or []],
        "codes": [code_obj(c) for c in codes or []],
        "rate_override": aff.get("rate_override"),
        "metadata": aff.get("metadata") or {},
        "created_at": aff["created_at"],
    }


def referral_obj(r: dict) -> dict:
    return {
        "id": r["_id"],
        "object": "referral",
        "affiliate_id": r["affiliate_id"],
        "campaign_id": r.get("campaign_id"),
        "source": r["source"],
        "status": r["status"],
        "email": r.get("email"),
        "user_id": r.get("external_user_id"),
        "stripe_customer_id": r.get("stripe_customer_id"),
        "flagged": bool(r.get("flags")) and not r.get("flags_cleared"),
        "rejected": bool(r.get("rejected")),
        "first_paid_at": r.get("first_paid_at"),
        "created_at": r["created_at"],
    }


def reward_obj(r: dict, referral: dict | None = None) -> dict:
    """referral: so a handler knows who to give it to without another call."""
    referral = referral or {}
    return {
        "id": r["_id"],
        "object": "reward",
        "recipient": r["recipient"],
        "description": r["description"],
        "trigger": r["trigger"],
        "status": r["status"],
        "held": bool(r.get("held")),
        "affiliate_id": r["affiliate_id"],
        "referral_id": r["referral_id"],
        "campaign_id": r["campaign_id"],
        "customer": {"email": referral.get("email"), "user_id": referral.get("external_user_id"), "stripe_customer_id": referral.get("stripe_customer_id")},
        "note": r.get("note"),
        "fulfilled_at": r.get("fulfilled_at"),
        "created_at": r["created_at"],
    }


def commission_obj(c: dict) -> dict:
    kind = "lead" if c.get("kind") == "lead" else "clawback" if c.get("clawback_of") else "sale"
    return {
        "id": c["_id"],
        "object": "commission",
        "kind": kind,
        "affiliate_id": c["affiliate_id"],
        "referral_id": c.get("referral_id"),
        "campaign_id": c.get("campaign_id"),
        "amount_cents": c["amount_cents"],
        "currency": c["currency"],
        "sale_amount_cents": c.get("base_cents", 0),
        "status": c["status"],
        "held_for_review": bool(c.get("held")),
        "source": c["source_key"],
        "due_at": c["due_at"],
        "paid_at": c.get("paid_at"),
        "payout_id": c.get("payout_id"),
        "void_reason": c.get("void_reason"),
        "created_at": c["created_at"],
    }


def payout_obj(p: dict) -> dict:
    return {
        "id": p["_id"],
        "object": "payout",
        "method": p["method"],
        "status": p["status"],
        "currency": p["currency"],
        "total_cents": p["total_cents"],
        "fee_cents": p.get("fee_cents", 0),
        "reference": p.get("reference"),
        "items": [
            {"affiliate_id": i["affiliate_id"], "amount_cents": i["amount_cents"], "commission_ids": i["commission_ids"], "status": i.get("status") or ("failed" if i.get("error") else p["status"]), "error": i.get("error")}
            for i in p["items"]
        ],
        "paid_at": p.get("paid_at"),
        "created_at": p["created_at"],
    }
