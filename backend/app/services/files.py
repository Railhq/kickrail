"""Files a program uploads: its logo and favicon, and the asset library's images and
downloads. Kept in Mongo as one document each, so there is no second store to run;
the per-file cap keeps every document well under Mongo's 16 MB limit.

Served publicly at /api/files/<id>/<name>. Ids are random, so a file is only found by
someone given its link, the same as any CDN upload."""

from datetime import UTC, datetime
from urllib.parse import quote

from bson import Binary
from pymongo.asynchronous.database import AsyncDatabase

from ..config import get_settings
from ..ids import new_id

MAX_BYTES = {"asset": 10 * 1024 * 1024, "logo": 1024 * 1024, "favicon": 256 * 1024}
PROGRAM_BYTES = 250 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon"}


class FileError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"


def url(f: dict) -> str:
    return f"{get_settings().public_url}/api/files/{f['_id']}/{quote(f['name'])}"


def meta(f: dict) -> dict:
    return {"id": f["_id"], "name": f["name"], "content_type": f["content_type"], "size": f["size"], "url": url(f)}


async def used_bytes(db: AsyncDatabase, merchant_id: str) -> int:
    rows = await (await db.files.aggregate([{"$match": {"merchant_id": merchant_id}}, {"$group": {"_id": None, "n": {"$sum": "$size"}}}])).to_list(None)
    return rows[0]["n"] if rows else 0


async def store(db: AsyncDatabase, merchant_id: str, kind: str, name: str, content_type: str, data: bytes) -> dict:
    if kind not in MAX_BYTES:
        raise FileError(f"unknown file kind: {kind}")
    if not data:
        raise FileError("the file is empty")
    if len(data) > MAX_BYTES[kind]:
        raise FileError(f"that file is {human(len(data))}; the limit is {human(MAX_BYTES[kind])}", 413)
    content_type = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if kind != "asset" and content_type not in IMAGE_TYPES:
        raise FileError("upload a PNG, JPEG, GIF, WebP, SVG or ICO image")
    if await used_bytes(db, merchant_id) + len(data) > PROGRAM_BYTES:
        raise FileError(f"this program has used its {human(PROGRAM_BYTES)} of file storage; delete some assets first", 413)
    name = "".join(c for c in name.strip().replace("/", "_").replace("\\", "_") if c.isprintable())[:120] or "file"
    doc = {"_id": new_id("fil"), "merchant_id": merchant_id, "kind": kind, "name": name, "content_type": content_type, "size": len(data), "data": Binary(data), "created_at": datetime.now(UTC)}
    await db.files.insert_one(doc)
    return doc


async def remove(db: AsyncDatabase, merchant_id: str, file_id: str) -> None:
    await db.files.delete_one({"_id": file_id, "merchant_id": merchant_id})
