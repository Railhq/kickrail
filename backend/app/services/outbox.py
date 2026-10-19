"""Everything Kickrail sends out: merchant webhooks and emails.

Domain code only writes to the outbox (emit / queue_email), so a slow or dead
receiver never holds up a Stripe webhook or a dashboard click. The dispatcher
delivers what is due and retries failures with backoff:

  events            one row per thing that happened, the payload webhooks carry
  webhook_deliveries one row per (event, endpoint), with attempts and status
  emails            one row per message

Webhook requests are signed like Stripe's: header Kickrail-Signature: t=<unix>,v1=<hex>
where v1 = HMAC-SHA256(endpoint secret, f"{t}.{body}").
"""

import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr

import httpx
from fastapi.encoders import jsonable_encoder
from pymongo.asynchronous.database import AsyncDatabase

from ..config import get_settings
from ..crypto import decrypt
from ..ids import new_id

log = logging.getLogger(__name__)

EVENT_TYPES = [
    "affiliate.created",
    "affiliate.updated",
    "referral.created",
    "referral.updated",
    "referral.converted",
    "referral.deleted",
    "commission.created",
    "commission.updated",
    "commission.deleted",
    "payout.due",
    "payout.paid",
    "payout.failed",
    "payout.undone",
]

# Minutes to wait after the Nth failure. After the last one the delivery is given up.
RETRY_MINUTES = [1, 5, 30, 120, 480, 1440]
STALE_LOCK = timedelta(minutes=5)

HttpPost = Callable[[str, str, dict], Awaitable[tuple[int, str]]]
SendMail = Callable[[dict], Awaitable[None]]


async def _http_post(url: str, body: str, headers: dict) -> tuple[int, str]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
        r = await c.post(url, content=body, headers=headers)
        return r.status_code, r.text[:500]


def _smtp_send(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_starttls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def _brevo_send(mail: dict) -> None:
    name, addr = parseaddr(mail["from"])
    body: dict = {"sender": {"name": name, "email": addr} if name else {"email": addr}, "to": [{"email": mail["to"]}], "subject": mail["subject"], "textContent": mail["text"], "tags": ["kickrail", mail.get("kind", "email")]}
    if mail.get("html"):
        body["htmlContent"] = mail["html"]
    if mail.get("reply_to"):
        body["replyTo"] = {"email": parseaddr(mail["reply_to"])[1]}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.brevo.com/v3/smtp/email", json=body, headers={"api-key": get_settings().brevo_api_key, "accept": "application/json"})
    if r.status_code >= 300:
        raise RuntimeError(f"Brevo {r.status_code}: {r.text[:300]}")


async def _send_mail(mail: dict) -> None:
    if get_settings().brevo_api_key:
        return await _brevo_send(mail)
    msg = EmailMessage()
    msg["From"] = mail["from"]
    msg["To"] = mail["to"]
    msg["Subject"] = mail["subject"]
    if mail.get("reply_to"):
        msg["Reply-To"] = mail["reply_to"]
    msg.set_content(mail["text"])
    if mail.get("html"):
        msg.add_alternative(mail["html"], subtype="html")
    await asyncio.to_thread(_smtp_send, msg)


# Swapped out in tests.
http_post: HttpPost = _http_post
send_mail: SendMail = _send_mail

_wake = asyncio.Event()


def wake() -> None:
    _wake.set()


def sign(secret: str, body: str, t: int | None = None) -> str:
    t = t or int(time.time())
    return f"t={t},v1={hmac.new(secret.encode(), f'{t}.{body}'.encode(), hashlib.sha256).hexdigest()}"


async def emit(db: AsyncDatabase, merchant_id: str, type_: str, data: dict) -> str:
    now = datetime.now(UTC)
    event = {"_id": new_id("evt"), "merchant_id": merchant_id, "type": type_, "data": jsonable_encoder(data), "created_at": now}
    await db.events.insert_one(event)
    endpoints = await db.webhook_endpoints.find({"merchant_id": merchant_id, "enabled": True, "events": {"$in": [type_, "*"]}}).to_list(None)
    if endpoints:
        await db.webhook_deliveries.insert_many(
            [
                {"_id": new_id("whd"), "merchant_id": merchant_id, "endpoint_id": ep["_id"], "event_id": event["_id"], "type": type_, "status": "pending", "attempts": 0, "next_attempt_at": now, "created_at": now}
                for ep in endpoints
            ]
        )
        _wake.set()
    return event["_id"]


def event_body(event: dict) -> str:
    return json.dumps({"id": event["_id"], "type": event["type"], "created": event["created_at"].isoformat(), "data": event["data"]}, separators=(",", ":"))


ACCOUNT_KINDS = ("verify_email", "password_reset")


async def queue_email(db: AsyncDatabase, to: str, subject: str, text: str, html: str | None = None, *, kind: str, merchant_id: str | None = None, from_name: str | None = None, reply_to: str | None = None) -> None:
    sender = get_settings().mail_from
    if from_name:
        # "Codemia via Kickrail <no-reply@kickrail.com>": the program's name, Kickrail's address.
        addr = sender.split("<")[-1].rstrip(">") if "<" in sender else sender
        sender = f"{from_name.replace('<', '').replace('>', '').replace('"', '')}{get_settings().mail_via} <{addr}>"
    now = datetime.now(UTC)
    await db.emails.insert_one(
        {"_id": new_id("eml"), "merchant_id": merchant_id, "kind": kind, "to": to, "from": sender, "reply_to": reply_to, "subject": subject, "text": text, "html": html, "status": "pending", "attempts": 0, "next_attempt_at": now, "created_at": now}
    )
    _wake.set()


def _backoff(attempts: int) -> timedelta | None:
    return timedelta(minutes=RETRY_MINUTES[attempts - 1]) if attempts <= len(RETRY_MINUTES) else None


async def _claim(coll, now: datetime):
    """Take one due item, so two dispatchers never send the same thing."""
    return await coll.find_one_and_update(
        {"$or": [{"status": "pending", "next_attempt_at": {"$lte": now}}, {"status": "sending", "locked_at": {"$lte": now - STALE_LOCK}}]},
        {"$set": {"status": "sending", "locked_at": now}},
        sort=[("next_attempt_at", 1)],
    )


async def _fail(coll, item: dict, error: str, now: datetime) -> None:
    attempts = item["attempts"] + 1
    wait = _backoff(attempts)
    s = {"attempts": attempts, "last_error": error[:500], "last_attempt_at": now}
    s |= {"status": "pending", "next_attempt_at": now + wait} if wait else {"status": "failed"}
    await coll.update_one({"_id": item["_id"]}, {"$set": s, "$unset": {"locked_at": ""}})


async def deliver_webhook(db: AsyncDatabase, d: dict, now: datetime) -> str:
    ep = await db.webhook_endpoints.find_one({"_id": d["endpoint_id"]})
    event = await db.events.find_one({"_id": d["event_id"]})
    if not ep or not event:
        await db.webhook_deliveries.update_one({"_id": d["_id"]}, {"$set": {"status": "failed", "last_error": "endpoint or event deleted"}})
        return "failed"
    body = event_body(event)
    headers = {"content-type": "application/json", "user-agent": "Kickrail-Webhooks/1", "kickrail-signature": sign(decrypt(ep["secret_enc"]), body), "kickrail-event": event["type"]}
    try:
        status, text = await http_post(ep["url"], body, headers)
    except Exception as e:  # network error, timeout, bad URL
        await _fail(db.webhook_deliveries, d, f"{type(e).__name__}: {e}", now)
        return "error"
    if 200 <= status < 300:
        await db.webhook_deliveries.update_one(
            {"_id": d["_id"]}, {"$set": {"status": "delivered", "response_status": status, "delivered_at": now, "last_attempt_at": now}, "$inc": {"attempts": 1}, "$unset": {"locked_at": ""}}
        )
        return "delivered"
    await db.webhook_deliveries.update_one({"_id": d["_id"]}, {"$set": {"response_status": status, "response_body": text}})
    await _fail(db.webhook_deliveries, d, f"HTTP {status}", now)
    return "error"


async def deliver_email(db: AsyncDatabase, mail: dict, now: datetime) -> str:
    s = get_settings()
    skip = {d.strip().lower() for d in s.mail_skip_domains.split(",") if d.strip()}
    if (not s.mail_enabled and send_mail is _send_mail) or mail["to"].rsplit("@", 1)[-1].lower() in skip:
        await db.emails.update_one({"_id": mail["_id"]}, {"$set": {"status": "logged", "sent_at": now}, "$unset": {"locked_at": ""}})
        # Account mail carries a link someone needs, so print it where a developer can click it.
        log.info("email (not sent) to %s: %s%s", mail["to"], mail["subject"], f"\n{mail['text']}" if mail.get("kind") in ACCOUNT_KINDS else "")
        return "logged"
    try:
        await send_mail(mail)
    except Exception as e:
        await _fail(db.emails, mail, f"{type(e).__name__}: {e}", now)
        return "error"
    await db.emails.update_one({"_id": mail["_id"]}, {"$set": {"status": "sent", "sent_at": now}, "$inc": {"attempts": 1}, "$unset": {"locked_at": ""}})
    return "sent"


async def deliver_due(db: AsyncDatabase, now: datetime | None = None, limit: int = 100) -> int:
    """Send everything that is due. Returns how many items were attempted."""
    now = now or datetime.now(UTC)
    n = 0
    for coll, deliver in ((db.webhook_deliveries, deliver_webhook), (db.emails, deliver_email)):
        while n < limit and (item := await _claim(coll, now)):
            await deliver(db, item, now)
            n += 1
    return n


async def run_dispatcher(
    db: AsyncDatabase, extra: Callable[[AsyncDatabase], Awaitable[None]] | None = None, each: Callable[[AsyncDatabase], Awaitable[object]] | None = None
) -> None:
    """Runs for the life of the app. Wakes on new work or every 15 seconds. `each` runs
    on every pass, `extra` every 5 minutes."""
    last_extra = 0.0
    while True:
        try:
            await deliver_due(db)
            if each:
                await each(db)
            if extra and time.monotonic() - last_extra > 300:
                last_extra = time.monotonic()
                await extra(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("dispatcher pass failed")
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=15)
        except TimeoutError:
            pass
