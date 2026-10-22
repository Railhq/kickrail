"""The asset library: logos, banners, copy and links a program hands its affiliates.
Drafts are the merchant's alone; published assets show in every affiliate's portal,
with links and copy already carrying that affiliate's own link."""

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, HttpUrl

from ..security import current_merchant, db_dep
from ..ids import new_id
from ..services import audit, files
from ..services.assets import asset_out

router = APIRouter(tags=["assets"])

Kind = Literal["image", "file", "link", "text"]
Status = Literal["draft", "published"]


# ---------- uploads ----------


@router.post("/merchant/files")
async def upload(request: Request, kind: Literal["asset", "logo", "favicon"] = "asset", name: str = "file", m=Depends(current_merchant), db=Depends(db_dep)):
    """The raw file is the request body, so no multipart parser is needed."""
    if int(request.headers.get("content-length") or 0) > files.MAX_BYTES[kind]:
        raise HTTPException(413, f"the limit is {files.human(files.MAX_BYTES[kind])}")
    data = await request.body()
    try:
        f = await files.store(db, m["_id"], kind, name, request.headers.get("content-type", ""), data)
    except files.FileError as e:
        raise HTTPException(e.status, str(e))
    return files.meta(f)


@router.get("/files/{file_id}/{name}")
async def serve(file_id: str, name: str, db=Depends(db_dep)):
    f = await db.files.find_one({"_id": file_id})
    if not f:
        raise HTTPException(404, "file not found")
    image = f["content_type"] in files.IMAGE_TYPES
    headers = {
        "cache-control": "public, max-age=31536000, immutable",
        "x-content-type-options": "nosniff",
        # An uploaded SVG or HTML file opened directly can't run scripts on our origin.
        "content-security-policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
        "content-disposition": f"{'inline' if image else 'attachment'}; filename*=UTF-8''{re.sub(r'[^A-Za-z0-9._-]', '_', f['name'])}",
    }
    return Response(bytes(f["data"]), media_type=f["content_type"] if image else "application/octet-stream", headers=headers)


# ---------- library ----------


class AssetIn(BaseModel):
    type: Kind
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    status: Status = "draft"
    url: HttpUrl | None = None
    text: str = Field(default="", max_length=5000)
    file_id: str | None = None


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    status: Status | None = None
    url: HttpUrl | None = None
    text: str | None = Field(default=None, max_length=5000)
    file_id: str | None = None


async def _content(db, m: dict, type_: str, url: HttpUrl | None, text: str | None, file_id: str | None) -> dict:
    """The fields that hold an asset's content, checked for its type."""
    if type_ == "link":
        if not url:
            raise HTTPException(422, "a link asset needs a URL")
        return {"url": str(url)}
    if type_ == "text":
        if not (text or "").strip():
            raise HTTPException(422, "a text asset needs some text")
        return {"text": text.strip()}
    f = await db.files.find_one({"_id": file_id, "merchant_id": m["_id"], "kind": "asset"}, {"data": 0}) if file_id else None
    if not f:
        raise HTTPException(422, "upload the file first")
    if type_ == "image" and f["content_type"] not in files.IMAGE_TYPES:
        raise HTTPException(422, "that file isn't an image; add it as a file instead")
    return {"file_id": f["_id"]}


@router.get("/merchant/assets")
async def list_assets(
    status: Status | None = None, type: Kind | None = None, q: str = "", sort: Literal["newest", "oldest", "name"] = "newest",
    m=Depends(current_merchant), db=Depends(db_dep),
):
    query: dict = {"merchant_id": m["_id"]}
    if type:
        query["type"] = type
    if q.strip():
        query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    counts = {"all": 0, "published": 0, "draft": 0}
    async for row in await db.assets.aggregate([{"$match": query}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
        counts["all"] += row["n"]
    if status:
        query["status"] = status
    order = {"newest": [("created_at", -1)], "oldest": [("created_at", 1)], "name": [("name_lower", 1)]}[sort]
    rows = await db.assets.find(query).sort(order).to_list(500)
    return {"items": [await asset_out(db, a) for a in rows], "counts": counts, "storage": {"used": await files.used_bytes(db, m["_id"]), "limit": files.PROGRAM_BYTES}}


@router.post("/merchant/assets")
async def create_asset(body: AssetIn, m=Depends(current_merchant), db=Depends(db_dep)):
    if await db.assets.count_documents({"merchant_id": m["_id"]}) >= 500:
        raise HTTPException(422, "a program can have at most 500 assets")
    now = datetime.now(UTC)
    doc = {
        "_id": new_id("ast"), "merchant_id": m["_id"], "type": body.type, "name": body.name.strip(), "name_lower": body.name.strip().lower(),
        "description": body.description.strip(), "status": body.status, "created_at": now, "updated_at": now,
        **await _content(db, m, body.type, body.url, body.text, body.file_id),
    }
    await db.assets.insert_one(doc)
    await audit.record(db, m["_id"], "asset.created", doc["_id"], name=doc["name"], status=doc["status"])
    return await asset_out(db, doc)


@router.patch("/merchant/assets/{asset_id}")
async def update_asset(asset_id: str, body: AssetPatch, m=Depends(current_merchant), db=Depends(db_dep)):
    a = await db.assets.find_one({"_id": asset_id, "merchant_id": m["_id"]})
    if not a:
        raise HTTPException(404, "asset not found")
    s: dict = {"updated_at": datetime.now(UTC)}
    if body.name is not None:
        s["name"], s["name_lower"] = body.name.strip(), body.name.strip().lower()
    if body.description is not None:
        s["description"] = body.description.strip()
    if body.status is not None:
        s["status"] = body.status
    if body.url is not None or body.text is not None or body.file_id is not None:
        s |= await _content(db, m, a["type"], body.url, body.text, body.file_id)
    await db.assets.update_one({"_id": asset_id}, {"$set": s})
    if "file_id" in s and a.get("file_id") and s["file_id"] != a["file_id"]:
        await files.remove(db, m["_id"], a["file_id"])
    if body.status and body.status != a["status"]:
        await audit.record(db, m["_id"], f"asset.{'published' if body.status == 'published' else 'unpublished'}", asset_id, name=s.get("name", a["name"]))
    return await asset_out(db, {**a, **s})


@router.delete("/merchant/assets/{asset_id}")
async def delete_asset(asset_id: str, m=Depends(current_merchant), db=Depends(db_dep)):
    a = await db.assets.find_one_and_delete({"_id": asset_id, "merchant_id": m["_id"]})
    if not a:
        raise HTTPException(404, "asset not found")
    if a.get("file_id"):
        await files.remove(db, m["_id"], a["file_id"])
    await audit.record(db, m["_id"], "asset.deleted", asset_id, name=a["name"])
    return {"ok": True}
