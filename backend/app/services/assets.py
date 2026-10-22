"""How assets look to the merchant, and to one affiliate in their portal."""

from pymongo.asynchronous.database import AsyncDatabase

from ..serializers import affiliate_url
from . import affiliates, files


async def _file(db: AsyncDatabase, a: dict) -> dict | None:
    if not a.get("file_id"):
        return None
    f = await db.files.find_one({"_id": a["file_id"]}, {"data": 0})
    return files.meta(f) if f else None


async def asset_out(db: AsyncDatabase, a: dict) -> dict:
    return {
        "id": a["_id"], "type": a["type"], "name": a["name"], "description": a.get("description", ""), "status": a["status"],
        "url": a.get("url"), "text": a.get("text"), "file": await _file(db, a), "created_at": a["created_at"], "updated_at": a["updated_at"],
    }


def tracked(m: dict, token: str, url: str) -> str | None:
    """A link on the program's own site, turned into this affiliate's link to that page."""
    try:
        return affiliate_url(m, token, affiliates.check_landing(m, url))
    except affiliates.AffiliateError:
        return None


async def for_affiliate(db: AsyncDatabase, m: dict, aff: dict, link: str) -> list[dict]:
    """Published assets with the affiliate's own link filled in: {link} and {code} in copy,
    and links to the program's site rewritten to credit them."""
    out = []
    async for a in db.assets.find({"merchant_id": m["_id"], "status": "published"}).sort("created_at", -1).limit(500):
        item = {"id": a["_id"], "type": a["type"], "name": a["name"], "description": a.get("description", ""), "file": await _file(db, a)}
        if a["type"] == "link":
            item["url"] = tracked(m, aff["token"], a["url"]) or a["url"]
        elif a["type"] == "text":
            item["text"] = a["text"].replace("{link}", link).replace("{code}", aff.get("code") or "")
        if a["type"] in ("image", "file") and not item["file"]:
            continue
        out.append(item)
    return out
