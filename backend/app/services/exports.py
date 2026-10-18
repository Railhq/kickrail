"""CSV downloads of a program's affiliates, referrals and commissions, so leaving Kickrail
is as easy as arriving. Rows stream out in batches; big programs never load at once."""

import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime

from pymongo.asynchronous.database import AsyncDatabase

from ..serializers import affiliate_url

BATCH = 500


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict | list):
        return json.dumps(v, default=str) if v else ""
    s = str(v)
    # Spreadsheets run cells that start like a formula.
    return f"'{s}" if s[:1] in ("=", "+", "-", "@") and not s.lstrip("-").replace(".", "", 1).isdigit() else s


def _line(row: list) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerow([_cell(v) for v in row])
    return buf.getvalue()


def _money(cents: int | None) -> str:
    return "" if cents is None else f"{cents / 100:.2f}"


async def _batches(cursor) -> AsyncIterator[list[dict]]:
    batch = []
    async for doc in cursor:
        batch.append(doc)
        if len(batch) >= BATCH:
            yield batch
            batch = []
    if batch:
        yield batch


async def _emails(db: AsyncDatabase, affiliate_ids: set[str]) -> dict[str, dict]:
    """affiliate id -> {email, name}."""
    affs = {a["_id"]: a["user_id"] async for a in db.affiliates.find({"_id": {"$in": list(affiliate_ids)}}, {"user_id": 1})}
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": list(affs.values())}}, {"email": 1, "name": 1})}
    return {aid: users.get(uid, {}) for aid, uid in affs.items()}


async def affiliates_csv(db: AsyncDatabase, m: dict) -> AsyncIterator[str]:
    yield _line(["id", "name", "email", "status", "campaign", "link", "token", "code", "other_links", "other_codes", "paypal_email", "metadata", "created_at"])
    campaigns = {c["_id"]: c async for c in db.campaigns.find({"merchant_id": m["_id"]}, {"name": 1, "landing_url": 1})}
    async for batch in _batches(db.affiliates.find({"merchant_id": m["_id"]}).sort("created_at", 1)):
        ids = [a["_id"] for a in batch]
        users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [a["user_id"] for a in batch]}}, {"email": 1, "name": 1, "payout_details": 1})}
        links: dict[str, list[str]] = {}
        async for l in db.affiliate_links.find({"affiliate_id": {"$in": ids}}, {"affiliate_id": 1, "token": 1}):
            links.setdefault(l["affiliate_id"], []).append(l["token"])
        codes: dict[str, list[str]] = {}
        async for c in db.affiliate_codes.find({"affiliate_id": {"$in": ids}}, {"affiliate_id": 1, "code": 1}):
            codes.setdefault(c["affiliate_id"], []).append(c["code"])
        out = []
        for a in batch:
            u = users.get(a["user_id"], {})
            camp = campaigns.get(a["campaign_id"], {})
            d = u.get("payout_details") or {}
            out.append(_line([
                a["_id"], u.get("name"), u.get("email"), a["status"], camp.get("name"), affiliate_url(m, a["token"], camp.get("landing_url")), a["token"], a.get("code"),
                " ".join(links.get(a["_id"], [])), " ".join(codes.get(a["_id"], [])), d.get("value") if d.get("method") == "paypal" else None, a.get("metadata"), a["created_at"],
            ]))
        yield "".join(out)


async def referrals_csv(db: AsyncDatabase, m: dict) -> AsyncIterator[str]:
    yield _line(["id", "affiliate_id", "affiliate_email", "email", "status", "stripe_customer_id", "external_user_id", "source", "flagged", "created_at", "first_paid_at"])
    async for batch in _batches(db.referrals.find({"merchant_id": m["_id"]}).sort("created_at", 1)):
        affs = await _emails(db, {r["affiliate_id"] for r in batch})
        yield "".join(
            _line([
                r["_id"], r["affiliate_id"], affs.get(r["affiliate_id"], {}).get("email"), r.get("email"), r["status"], r.get("stripe_customer_id"), r.get("external_user_id"),
                r.get("source"), "yes" if r.get("flags") and not r.get("flags_cleared") else "", r["created_at"], r.get("first_paid_at"),
            ])
            for r in batch
        )


async def commissions_csv(db: AsyncDatabase, m: dict) -> AsyncIterator[str]:
    yield _line(["id", "affiliate_id", "affiliate_email", "referral_id", "customer_email", "kind", "status", "held", "amount", "currency", "sale_amount", "refunded", "due_at", "paid_at", "payout_id", "created_at"])
    async for batch in _batches(db.commissions.find({"merchant_id": m["_id"]}).sort("created_at", 1)):
        affs = await _emails(db, {c["affiliate_id"] for c in batch})
        refs = {r["_id"]: r.get("email") async for r in db.referrals.find({"_id": {"$in": [c["referral_id"] for c in batch if c.get("referral_id")]}}, {"email": 1})}
        yield "".join(
            _line([
                c["_id"], c["affiliate_id"], affs.get(c["affiliate_id"], {}).get("email"), c.get("referral_id"), refs.get(c.get("referral_id")), c.get("kind", "sale"), c["status"],
                "yes" if c.get("held") else "", _money(c["amount_cents"]), c["currency"].upper(), _money(c.get("base_cents")), _money(c.get("refunded_cents") or 0),
                c.get("due_at"), c.get("paid_at"), c.get("payout_id"), c["created_at"],
            ])
            for c in batch
        )


EXPORTS = {"affiliates": affiliates_csv, "referrals": referrals_csv, "commissions": commissions_csv}
