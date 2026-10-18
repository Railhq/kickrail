"""Browser-facing tracking endpoints. Reached through the web proxy (or the
merchant's own first-party proxy), never with credentials."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from pymongo.errors import DuplicateKeyError

from ..config import get_settings
from ..security import client_ip_hash, db_dep
from ..services.affiliates import program_public
from ..services.referrals import AttachInput, affiliate_by_token, attach_referral

router = APIRouter(tags=["public"])

SCRIPT = (Path(__file__).parent.parent / "static" / "kr.js").read_text()
CLICK_ID = re.compile(r"^kr_[A-Za-z0-9]{16,40}$")
CORS = {"access-control-allow-origin": "*", "access-control-allow-methods": "POST, OPTIONS", "access-control-allow-headers": "content-type"}


@router.get("/kr.js")
async def script(request: Request, k: str = "", api: str = "", db=Depends(db_dep)):
    m = await db.merchants.find_one({"public_key": k}) if k else None
    if not m:
        return Response("console.warn('Kickrail: unknown or missing ?k= key');", media_type="application/javascript")
    await _seen(db, m, request.headers.get("referer", ""))
    # api= lets a merchant serve everything through their own domain (ad blockers
    # leave first-party paths alone), e.g. /kr proxied to Kickrail's /api.
    base = api if api.startswith("/") and not api.startswith("//") else f"{get_settings().public_url}/api"
    config = {"key": m["public_key"], "api": base, "params": m["settings"]["param_names"], "days": m["settings"]["cookie_days"]}
    body = SCRIPT.replace("__KR_CONFIG__", json.dumps(config), 1)
    return Response(body, media_type="application/javascript", headers={"cache-control": "public, max-age=300"})


async def _seen(db, m: dict, referer: str) -> None:
    """Note that the script loaded on a live page (at most hourly), so setup can tell it's installed."""
    now = datetime.now(UTC)
    last = (m.get("tracking") or {}).get("script_seen_at")
    if last and last.replace(tzinfo=UTC) > now - timedelta(hours=1):
        return
    host = urlsplit(referer).hostname if referer else None
    await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"tracking.script_seen_at": now, "tracking.script_seen_on": host}})


async def _json(request: Request) -> dict:
    try:
        data = json.loads((await request.body())[:8192] or b"{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


@router.options("/track/{_path}")
async def preflight(_path: str):
    return Response(status_code=204, headers=CORS)


@router.post("/track/click")
async def click(request: Request, db=Depends(db_dep)):
    b = await _json(request)
    click_id, token = str(b.get("id", "")), str(b.get("token", "")).lower()[:64]
    m = await db.merchants.find_one({"public_key": str(b.get("key", ""))}) if b.get("key") else None
    if not m or not CLICK_ID.match(click_id) or not token:
        return Response(status_code=204, headers=CORS)
    test = bool(b.get("test"))
    # Test clicks are recorded for pending affiliates too, so they can verify a link before approval.
    aff = await affiliate_by_token(db, m["_id"], token, approved_only=not test)
    if aff:
        try:
            await db.clicks.insert_one(
                {
                    "_id": click_id,
                    "merchant_id": m["_id"],
                    "affiliate_id": aff["_id"],
                    "token": token,
                    "landing_url": str(b.get("url", ""))[:1000],
                    "referrer": str(b.get("referrer", ""))[:1000],
                    "ip_hash": client_ip_hash(request),
                    "user_agent": request.headers.get("user-agent", "")[:300],
                    "test": test,
                    "created_at": datetime.now(UTC),
                }
            )
        except DuplicateKeyError:
            # kr.js reuses the click id when the same link is opened again, so a real visit after a
            # kr_test=1 one in the same browser would be dropped. Promote the test click instead.
            if not test:
                await db.clicks.update_one(
                    {"_id": click_id, "merchant_id": m["_id"], "token": token, "test": True},
                    {"$set": {"test": False, "affiliate_id": aff["_id"], "landing_url": str(b.get("url", ""))[:1000], "referrer": str(b.get("referrer", ""))[:1000], "created_at": datetime.now(UTC)}},
                )
    return Response(status_code=204, headers=CORS)


@router.post("/track/lead")
async def lead(request: Request, db=Depends(db_dep)):
    b = await _json(request)
    m = await db.merchants.find_one({"public_key": str(b.get("key", ""))}) if b.get("key") else None
    email = str(b.get("email", "")).strip()
    if m and CLICK_ID.match(str(b.get("id", ""))) and "@" in email:
        await attach_referral(db, m, AttachInput(click_id=b["id"], email=email[:200], ip_hash=client_ip_hash(request), auto=b.get("auto") is True))
    return Response(status_code=204, headers=CORS)


@router.get("/tls/ask")
async def tls_ask(domain: str = "", db=Depends(db_dep)):
    """The portal proxy (Caddy on-demand TLS) asks this before getting a certificate
    for a hostname. Only verified portal domains get one."""
    host = domain.lower().strip().rstrip(".")
    if host and await db.merchants.find_one({"portal_domains": {"$elemMatch": {"host": host, "verified": True}}}, {"_id": 1}):
        return Response(status_code=200)
    return Response(status_code=404)


@router.get("/domains/{host}")
async def domain(host: str, db=Depends(db_dep)):
    """Which program a custom portal domain belongs to. The web middleware calls this
    to serve the join page and portal on the merchant's own hostname."""
    m = await db.merchants.find_one({"portal_domains": {"$elemMatch": {"host": host.lower().split(":")[0], "verified": True}}})
    if not m:
        return Response(status_code=404)
    return program_public(m, None)
