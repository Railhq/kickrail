"""What happens when something happens: a webhook event for the merchant and, where
the program has it switched on, an email to the affiliate (or to the merchant team).

Everything goes through the outbox, so callers never wait on delivery."""

import html

from pymongo.asynchronous.database import AsyncDatabase

from ..config import get_settings
from ..domain.commission import describe_rule
from ..serializers import affiliate_obj, affiliate_url, commission_obj, payout_obj, portal_base, referral_obj
from .outbox import emit, queue_email

EMAIL_KINDS = {
    "welcome": "Welcome email when someone joins",
    "approved": "Approval email when you approve a pending affiliate",
    "commission": "Email the affiliate for every new commission",
    "payout": "Email the affiliate when a payout is sent",
    "new_affiliate": "Email your team when someone applies",
}


def email_on(m: dict, kind: str) -> bool:
    return (m.get("settings", {}).get("emails") or {}).get(kind, True)


def money(cents: int, currency: str) -> str:
    return f"{cents / 100:,.2f} {currency.upper()}"


def render(m: dict, heading: str, paragraphs: list[str], cta: tuple[str, str] | None = None, footer: str | None = None) -> tuple[str, str]:
    """Plain text plus a small HTML version in the program's colours."""
    footer = footer or f"{m['name']} affiliate program"
    b = m.get("branding") or {}
    color = b.get("color") or "#0f5e4b"
    text = "\n\n".join([heading, *paragraphs, *([f"{cta[0]}: {cta[1]}"] if cta else []), footer])
    logo = f'<img src="{html.escape(b["logo_url"])}" alt="{html.escape(m["name"])}" height="32" style="height:32px;margin-bottom:20px">' if b.get("logo_url") else f'<p style="font-weight:600;margin:0 0 20px">{html.escape(m["name"])}</p>'
    body = "".join(f'<p style="margin:0 0 14px;line-height:1.55">{html.escape(p)}</p>' for p in paragraphs)
    button = (
        f'<p style="margin:22px 0"><a href="{html.escape(cta[1])}" style="background:{html.escape(color)};color:#fff;padding:11px 18px;border-radius:8px;text-decoration:none;font-weight:600">{html.escape(cta[0])}</a></p>'
        if cta
        else ""
    )
    page = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1a1a17;max-width:520px;margin:0 auto;padding:28px 20px">'
        f"{logo}<h1 style=\"font-size:20px;margin:0 0 16px\">{html.escape(heading)}</h1>{body}{button}"
        f'<p style="margin-top:28px;font-size:12px;color:#77756c">{html.escape(footer)}</p></div>'
    )
    return text, page


async def _send(db: AsyncDatabase, m: dict, to: str, kind: str, subject: str, heading: str, paragraphs: list[str], cta: tuple[str, str] | None = None) -> None:
    text, page = render(m, heading, paragraphs, cta)
    owner = await db.users.find_one({"_id": m.get("owner_id")}, {"email": 1})
    await queue_email(db, to, subject, text, page, kind=kind, merchant_id=m["_id"], from_name=m["name"], reply_to=(m.get("branding") or {}).get("reply_to") or (owner or {}).get("email"))


async def account_email(db: AsyncDatabase, to: str, kind: str, subject: str, heading: str, paragraphs: list[str], cta: tuple[str, str]) -> None:
    """Kickrail's own mail about the person's login (verify, reset), not any program's."""
    text, page = render({"name": "Kickrail"}, heading, paragraphs, cta, footer="Kickrail. You got this because this address was used to sign in to Kickrail.")
    await queue_email(db, to, subject, text, page, kind=kind)


async def _aff_parts(db: AsyncDatabase, aff: dict) -> tuple[dict, list[dict], list[dict], dict | None]:
    user = await db.users.find_one({"_id": aff["user_id"]}) or {}
    links = await db.affiliate_links.find({"affiliate_id": aff["_id"]}).to_list(None)
    codes = await db.affiliate_codes.find({"affiliate_id": aff["_id"]}).to_list(None)
    campaign = await db.campaigns.find_one({"_id": aff.get("campaign_id")})
    return user, links, codes, campaign


async def affiliate_created(db: AsyncDatabase, m: dict, aff: dict, *, send_welcome: bool = True, claim_url: str | None = None) -> None:
    """claim_url: for accounts made through the API, the link that sets their password."""
    user, links, codes, campaign = await _aff_parts(db, aff)
    await emit(db, m["_id"], "affiliate.created", affiliate_obj(m, aff, user, links, codes, campaign))
    dashboard = claim_url or f"{portal_base(m)}/a/{aff['_id']}"
    if send_welcome and email_on(m, "welcome") and user.get("email"):
        if aff["status"] == "approved":
            await _approved_email(db, m, aff, user, "welcome", f"Welcome to the {m['name']} affiliate program", claim_url)
        else:
            await _send(
                db, m, user["email"], "welcome", f"We got your application to {m['name']}", "Application received",
                [f"Hi {user.get('name') or 'there'}, thanks for applying to the {m['name']} affiliate program.", "The team reviews new affiliates by hand. You'll get an email with your link as soon as you're approved."],
                ("Set your password" if claim_url else "Open your dashboard", dashboard),
            )
    if aff["status"] == "pending" and email_on(m, "new_affiliate"):
        members = await db.users.find({"_id": {"$in": m.get("member_ids", [])}}, {"email": 1}).to_list(None)
        for member in members:
            await _send(
                db, m, member["email"], "new_affiliate", f"New affiliate application: {user.get('name') or user.get('email')}", "Someone wants to promote you",
                [f"{user.get('name', '')} ({user.get('email', '')}) applied to join {m['name']}. Approve or decline them from the Affiliates page."],
                ("Review applications", f"{get_settings().public_url}/dashboard/affiliates"),
            )


async def _approved_email(db: AsyncDatabase, m: dict, aff: dict, user: dict, kind: str, subject: str, claim_url: str | None = None) -> None:
    campaign = await db.campaigns.find_one({"_id": aff["campaign_id"]})
    lines = [
        f"Hi {user.get('name') or 'there'}, you're approved to promote {m['name']}.",
        f"Your link: {affiliate_url(m, aff['token'], (campaign or {}).get('landing_url'))}",
    ]
    if aff.get("code"):
        lines.append(f"Your code: {aff['code']}" + (" (customers can type it at checkout)" if aff.get("stripe_promotion_code_id") else ""))
    if campaign:
        lines.append(f"You earn {describe_rule(campaign, aff)}.")
    if welcome := (m.get("branding") or {}).get("welcome_message"):
        lines.append(welcome)
    if claim_url:
        lines.append("Set a password to see your clicks, referrals and earnings.")
    cta = ("Set your password", claim_url) if claim_url else ("Open your dashboard", f"{portal_base(m)}/a/{aff['_id']}")
    await _send(db, m, user["email"], kind, subject, "You're in" if kind == "welcome" else "You're approved", lines, cta)


async def claim_invite(db: AsyncDatabase, m: dict, aff: dict, user: dict, claim_url: str) -> None:
    """For affiliates moved over from another tool: their link still works, and this sets a password."""
    await _approved_email(db, m, aff, user, "welcome", f"Your {m['name']} affiliate account has moved", claim_url)


async def affiliate_updated(db: AsyncDatabase, m: dict, aff: dict, old_status: str | None = None) -> None:
    user, links, codes, campaign = await _aff_parts(db, aff)
    await emit(db, m["_id"], "affiliate.updated", affiliate_obj(m, aff, user, links, codes, campaign) | {"previous_status": old_status})
    if old_status and old_status != "approved" and aff["status"] == "approved" and email_on(m, "approved") and user.get("email"):
        await _approved_email(db, m, aff, user, "approved", f"You're approved for the {m['name']} affiliate program")


async def referral_created(db: AsyncDatabase, merchant_id: str, r: dict) -> None:
    await emit(db, merchant_id, "referral.created", referral_obj(r))


async def referral_converted(db: AsyncDatabase, merchant_id: str, r: dict) -> None:
    await emit(db, merchant_id, "referral.converted", referral_obj(r))


async def commission_created(db: AsyncDatabase, m: dict, c: dict) -> None:
    await emit(db, m["_id"], "commission.created", commission_obj(c))
    if c["amount_cents"] <= 0 or not email_on(m, "commission"):
        return
    aff = await db.affiliates.find_one({"_id": c["affiliate_id"]})
    user = await db.users.find_one({"_id": aff["user_id"]}) if aff else None
    if not user:
        return
    what = "a new signup" if c.get("kind") == "lead" else "a payment from someone you referred"
    held = " It's held for review first, which usually means the team is checking it isn't a self-referral." if c.get("held") else ""
    await _send(
        db, m, user["email"], "commission", f"You earned {money(c['amount_cents'], c['currency'])} from {m['name']}", "New commission",
        [f"You earned {money(c['amount_cents'], c['currency'])} for {what}.", f"It becomes payable on {c['due_at']:%B %-d, %Y}, after the refund window.{held}"],
        ("See your earnings", f"{portal_base(m)}/a/{aff['_id']}"),
    )


async def commission_updated(db: AsyncDatabase, merchant_id: str, commission_id: str, type_: str = "commission.updated") -> None:
    c = await db.commissions.find_one({"_id": commission_id})
    if c:
        await emit(db, merchant_id, type_, commission_obj(c))


async def payout_paid(db: AsyncDatabase, m: dict, payout: dict, items: list[dict] | None = None, event: bool = True) -> None:
    """items: the lines that actually went out (a partial batch has failures too)."""
    if event:
        await emit(db, m["_id"], "payout.paid", payout_obj(payout))
    if not email_on(m, "payout"):
        return
    sent = items if items is not None else payout["items"]
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [i["user_id"] for i in sent]}})}
    how = {"stripe": "to your Stripe payout account", "paypal": "to your PayPal account", "manual": "using the payout details you saved"}[payout["method"]]
    for item in sent:
        user = users.get(item["user_id"])
        if not user:
            continue
        lines = [f"{m['name']} sent you {money(item['amount_cents'], payout['currency'])} {how}, covering {len(item['commission_ids'])} commission{'s' if len(item['commission_ids']) != 1 else ''}."]
        if payout.get("reference"):
            lines.append(f"Reference: {payout['reference']}")
        if payout["method"] == "manual":
            lines.append("Depending on the method it can take a few days to arrive.")
        await _send(db, m, user["email"], "payout", f"{m['name']} sent you {money(item['amount_cents'], payout['currency'])}", "Payout sent", lines, ("See your payouts", f"{portal_base(m)}/a/{item['affiliate_id']}"))


async def payout_event(db: AsyncDatabase, merchant_id: str, type_: str, payout_id: str) -> None:
    p = await db.payouts.find_one({"_id": payout_id})
    if p:
        await emit(db, merchant_id, type_, payout_obj(p))

