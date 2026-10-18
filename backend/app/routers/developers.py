"""Webhook endpoints and the delivery logs: what Kickrail sent the merchant's
servers, and the emails it sent their affiliates."""

import asyncio
import ipaddress
import socket
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import plans
from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..ids import new_id, random_id
from ..security import current_merchant, db_dep
from ..services import outbox
from ..services.outbox import EVENT_TYPES

router = APIRouter(prefix="/merchant", tags=["developers"])


def _local_dev() -> bool:
    return get_settings().public_url.startswith("http://localhost")


async def check_url(url: str) -> str:
    """https only, and never an address inside our own network."""
    parts = urlsplit(url.strip())
    host = parts.hostname or ""
    if parts.scheme != "https" and not (_local_dev() and parts.scheme == "http"):
        raise HTTPException(422, "webhook URLs must use https")
    if not host or parts.username or parts.password:
        raise HTTPException(422, "enter a full URL like https://example.com/webhooks/kickrail")
    if _local_dev():
        return url.strip()
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise HTTPException(422, f"{host} doesn't resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise HTTPException(422, f"{host} resolves to a private address")
    return url.strip()


def endpoint_out(ep: dict, reveal: bool = False) -> dict:
    return {
        "id": ep["_id"],
        "url": ep["url"],
        "description": ep.get("description", ""),
        "events": ep["events"],
        "enabled": ep["enabled"],
        "created_at": ep["created_at"],
        **({"secret": decrypt(ep["secret_enc"])} if reveal else {"secret_hint": ep["secret_hint"]}),
    }


class EndpointIn(BaseModel):
    url: str = Field(max_length=500)
    description: str = Field(default="", max_length=200)
    events: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    enabled: bool = True


def _events(events: list[str]) -> list[str]:
    bad = [e for e in events if e != "*" and e not in EVENT_TYPES]
    if bad:
        raise HTTPException(422, f"unknown event types: {', '.join(bad)}")
    return ["*"] if "*" in events else sorted(set(events))


@router.get("/webhooks")
async def endpoints(m=Depends(current_merchant), db=Depends(db_dep)):
    rows = await db.webhook_endpoints.find({"merchant_id": m["_id"]}).sort("created_at", 1).to_list(None)
    return {"endpoints": [endpoint_out(e) for e in rows], "event_types": EVENT_TYPES}


@router.post("/webhooks")
async def create_endpoint(body: EndpointIn, m=Depends(current_merchant), db=Depends(db_dep)):
    plans.require(m, "webhooks")
    if await db.webhook_endpoints.count_documents({"merchant_id": m["_id"]}) >= 10:
        raise HTTPException(422, "you can have up to 10 endpoints")
    secret = f"whsec_{random_id(32)}"
    ep = {
        "_id": new_id("we"),
        "merchant_id": m["_id"],
        "url": await check_url(body.url),
        "description": body.description.strip(),
        "events": _events(body.events),
        "enabled": body.enabled,
        "secret_enc": encrypt(secret),
        "secret_hint": f"{secret[:10]}…",
        "created_at": datetime.now(UTC),
    }
    await db.webhook_endpoints.insert_one(ep)
    return endpoint_out(ep, reveal=True)


async def _ep(db, m: dict, endpoint_id: str) -> dict:
    ep = await db.webhook_endpoints.find_one({"_id": endpoint_id, "merchant_id": m["_id"]})
    if not ep:
        raise HTTPException(404, "endpoint not found")
    return ep


@router.put("/webhooks/{endpoint_id}")
async def update_endpoint(endpoint_id: str, body: EndpointIn, m=Depends(current_merchant), db=Depends(db_dep)):
    ep = await _ep(db, m, endpoint_id)
    s = {"url": await check_url(body.url), "description": body.description.strip(), "events": _events(body.events), "enabled": body.enabled}
    await db.webhook_endpoints.update_one({"_id": ep["_id"]}, {"$set": s})
    return endpoint_out(ep | s)


@router.get("/webhooks/{endpoint_id}/secret")
async def reveal_secret(endpoint_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    return endpoint_out(await _ep(db, m, endpoint_id), reveal=True)


@router.delete("/webhooks/{endpoint_id}")
async def delete_endpoint(endpoint_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    ep = await _ep(db, m, endpoint_id)
    await db.webhook_endpoints.delete_one({"_id": ep["_id"]})
    await db.webhook_deliveries.update_many({"endpoint_id": ep["_id"], "status": "pending"}, {"$set": {"status": "failed", "last_error": "endpoint deleted"}})
    return {"ok": True}


@router.post("/webhooks/{endpoint_id}/test")
async def send_test(endpoint_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    """Send a ping right now and report what the endpoint answered."""
    ep = await _ep(db, m, endpoint_id)
    now = datetime.now(UTC)
    event = {"_id": new_id("evt"), "merchant_id": m["_id"], "type": "ping", "data": {"message": "Kickrail test event", "endpoint_id": ep["_id"]}, "created_at": now}
    await db.events.insert_one(event)
    d = {"_id": new_id("whd"), "merchant_id": m["_id"], "endpoint_id": ep["_id"], "event_id": event["_id"], "type": "ping", "status": "sending", "attempts": len(outbox.RETRY_MINUTES), "next_attempt_at": now, "created_at": now, "test": True}
    await db.webhook_deliveries.insert_one(d)
    result = await outbox.deliver_webhook(db, d, now)
    row = await db.webhook_deliveries.find_one({"_id": d["_id"]})
    return {"ok": result == "delivered", **delivery_out(row)}


def delivery_out(d: dict) -> dict:
    return {
        "id": d["_id"],
        "endpoint_id": d["endpoint_id"],
        "event_id": d["event_id"],
        "type": d["type"],
        "status": d["status"],
        "attempts": d["attempts"],
        "response_status": d.get("response_status"),
        "response_body": d.get("response_body"),
        "last_error": d.get("last_error"),
        "next_attempt_at": d.get("next_attempt_at") if d["status"] == "pending" else None,
        "delivered_at": d.get("delivered_at"),
        "created_at": d["created_at"],
    }


@router.get("/webhooks/{endpoint_id}/deliveries")
async def deliveries(endpoint_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    ep = await _ep(db, m, endpoint_id)
    rows = await db.webhook_deliveries.find({"endpoint_id": ep["_id"]}).sort("created_at", -1).limit(100).to_list(None)
    events = {e["_id"]: e async for e in db.events.find({"_id": {"$in": [r["event_id"] for r in rows]}})}
    return [delivery_out(r) | {"payload": outbox.event_body(events[r["event_id"]]) if r["event_id"] in events else None} for r in rows]


@router.post("/webhooks/deliveries/{delivery_id}/retry")
async def retry(delivery_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    res = await db.webhook_deliveries.update_one(
        {"_id": delivery_id, "merchant_id": m["_id"], "status": {"$in": ["failed", "pending"]}},
        {"$set": {"status": "pending", "next_attempt_at": datetime.now(UTC), "attempts": 0}},
    )
    if not res.matched_count:
        raise HTTPException(404, "delivery not found or already delivered")
    outbox._wake.set()
    return {"ok": True}


@router.get("/emails")
async def emails(m=Depends(current_merchant), db=Depends(db_dep)):
    rows = await db.emails.find({"merchant_id": m["_id"]}, {"html": 0}).sort("created_at", -1).limit(200).to_list(None)
    return {
        "smtp_configured": get_settings().mail_enabled,
        "emails": [
            {"id": e["_id"], "kind": e["kind"], "to": e["to"], "subject": e["subject"], "text": e["text"], "status": e["status"], "last_error": e.get("last_error"), "sent_at": e.get("sent_at"), "created_at": e["created_at"]}
            for e in rows
        ],
    }
