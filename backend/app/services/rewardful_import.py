"""Moving a program over from Rewardful through Rewardful's REST API.

The merchant pastes their Rewardful API secret. It's used for this one run, kept only in
memory, and never stored or sent back. Every imported document carries `rewardful_id`, so
running the import again updates what's there instead of adding copies.

An import is quiet: no webhooks and no emails, apart from the "claim your account" emails
when the merchant asks for them. Affiliates keep their link tokens (`?via=` is one of
Kickrail's default link params) and coupon codes, referrals keep their Stripe customer so
renewals keep crediting, and unpaid commissions stay owed."""

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from .. import plans
from ..ids import new_id, random_id, sha256, slugify
from ..serializers import portal_base
from . import notify
from .affiliates import AffiliateError, check_landing
from .referrals import find_referral

log = logging.getLogger(__name__)

BASE = "https://api.getrewardful.com/v1"
# Rewardful allows 45 requests per 30 seconds.
RATE = (40, 30.0)
STALE_AFTER = 120  # seconds without progress before a run counts as stopped
MAX_WARNINGS = 50
STEPS = ("campaigns", "affiliates", "referrals", "commissions", "payouts")


class RewardfulError(Exception):
    pass


class Rewardful:
    def __init__(self, secret: str, base: str = BASE, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url=base, auth=(secret, ""), timeout=30, transport=transport)
        self._sent: deque[float] = deque()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def _throttle(self):
        n, window = RATE
        while len(self._sent) >= n:
            wait = self._sent[0] + window - time.monotonic()
            if wait <= 0:
                self._sent.popleft()
            else:
                await asyncio.sleep(wait)
        self._sent.append(time.monotonic())

    async def get(self, path: str, params: list[tuple[str, str | int]]) -> dict:
        for attempt in range(6):
            await self._throttle()
            try:
                r = await self._client.get(path, params=params)
            except httpx.HTTPError as e:
                if attempt == 5:
                    raise RewardfulError(f"could not reach Rewardful: {e}") from e
                await asyncio.sleep(2**attempt)
                continue
            if r.status_code == 401:
                raise RewardfulError("Rewardful didn't accept that API secret")
            if r.status_code == 429 or r.status_code >= 500:
                await asyncio.sleep(float(r.headers.get("retry-after") or 0) or min(30, 2**attempt * 2))
                continue
            if r.status_code >= 400:
                raise RewardfulError(f"Rewardful answered {r.status_code} for {path}")
            return r.json()
        raise RewardfulError(f"Rewardful kept refusing {path}; try again in a few minutes")

    async def pages(self, path: str, params: list[tuple[str, str | int]] = ()) -> AsyncIterator[tuple[list[dict], int]]:
        """Yields (rows, total_count) per page."""
        page = 1
        while page:
            body = await self.get(path, [*params, ("page", page), ("limit", 100)])
            p = body.get("pagination") or {}
            yield body.get("data") or [], p.get("total_count") or 0
            page = p.get("next_page")


def _time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _rule(c: dict) -> dict:
    if c.get("reward_type") == "amount":
        return {"type": "flat", "cents": int(c.get("commission_amount_cents") or 0), "currency": (c.get("commission_amount_currency") or "usd").lower()}
    return {"type": "percent", "bps": round(float(c.get("commission_percent") or 0) * 100)}


def _duration(c: dict) -> dict:
    if c.get("max_commissions") == 1:
        return {"mode": "once"}
    if c.get("max_commission_period_months"):
        return {"mode": "months", "months": int(c["max_commission_period_months"])}
    return {"mode": "forever"}


class Run:
    def __init__(self, db: AsyncDatabase, m: dict, import_id: str, api, send_claims: bool):
        self.db, self.m, self.id, self.api, self.send_claims = db, m, import_id, api, send_claims
        self.campaigns_map: dict[str, str] = {}
        self.affiliates_map: dict[str, dict] = {}
        self.referrals_map: dict[str, str] = {}
        self.counts = {s: 0 for s in STEPS}
        self.warnings: list[str] = []
        self._saved = 0.0

    def warn(self, msg: str):
        if len(self.warnings) < MAX_WARNINGS and msg not in self.warnings:
            self.warnings.append(msg)

    async def save(self, step: str, total: int | None = None, force: bool = False):
        now = time.monotonic()
        if not force and now - self._saved < 2:
            return
        self._saved = now
        s = {"step": step, "counts": self.counts, "warnings": self.warnings, "heartbeat_at": datetime.now(UTC)}
        if total is not None:
            s[f"totals.{step}"] = total
        await self.db.imports.update_one({"_id": self.id}, {"$set": s})

    async def run(self):
        for step in STEPS:
            await self.save(step, force=True)
            await getattr(self, step)()
            await self.save(step, force=True)

    # Campaigns -----------------------------------------------------------------

    async def campaigns(self):
        db, m = self.db, self.m
        default = await db.campaigns.find_one({"merchant_id": m["_id"], "is_default": True})
        room = plans.current(m)["campaigns"]
        async for rows, total in self.api.pages("/campaigns"):
            for c in rows:
                kr = await db.campaigns.find_one({"merchant_id": m["_id"], "rewardful_id": c["id"]})
                if not kr and c.get("default") and not default.get("rewardful_id"):
                    kr = default
                fields = {
                    "rewardful_id": c["id"],
                    "name": (c.get("name") or "Imported")[:60],
                    "rule": _rule(c),
                    "duration": _duration(c),
                    "hold_days": max(0, min(180, int(c.get("days_until_commissions_are_due") or 0))),
                    "min_payout_cents": int(c.get("minimum_payout_cents") or 0),
                }
                if c.get("max_commissions") and c["max_commissions"] > 1:
                    self.warn(f"Campaign {fields['name']}: Kickrail has no cap of {c['max_commissions']} commissions per referral, so it uses the month limit only.")
                if c.get("stripe_coupon_id"):
                    if plans.current(m)["creator_codes"]:
                        fields["stripe_coupon_id"] = c["stripe_coupon_id"]
                    else:
                        self.warn(f"Campaign {fields['name']}: its Stripe coupon needs the Starter plan or higher, so it wasn't carried over.")
                if c.get("url"):
                    try:
                        fields["landing_url"] = check_landing(m, c["url"])
                    except AffiliateError:
                        self.warn(f"Campaign {fields['name']}: its link URL {c['url']} isn't on your program website, so links point at the website.")
                if kr:
                    await db.campaigns.update_one({"_id": kr["_id"]}, {"$set": fields})
                    self.campaigns_map[c["id"]] = kr["_id"]
                elif room is not None and await db.campaigns.count_documents({"merchant_id": m["_id"]}) >= room:
                    self.warn(f"Campaign {fields['name']}: your plan has room for {room} campaign, so its affiliates joined your default campaign.")
                    self.campaigns_map[c["id"]] = default["_id"]
                    continue
                else:
                    doc = {"_id": new_id("cmp"), "merchant_id": m["_id"], **fields, "is_default": False, "public": False, "created_at": _time(c.get("created_at")) or datetime.now(UTC)}
                    if not c.get("private"):
                        doc |= {"public": True, "slug": (slugify(fields["name"])[:34] or "campaign")}
                    for attempt in range(3):
                        try:
                            await db.campaigns.insert_one(doc)
                            break
                        except DuplicateKeyError:
                            doc["slug"] = f"{doc['slug'][:34]}-{random_id(4).lower()}"
                    self.campaigns_map[c["id"]] = doc["_id"]
                self.counts["campaigns"] += 1
            await self.save("campaigns", total)

    # Affiliates ----------------------------------------------------------------

    async def _user(self, email: str, name: str, paypal: str | None) -> dict:
        """People new to Kickrail get an account with no password."""
        db, m = self.db, self.m
        user = await db.users.find_one({"email": email})
        if not user:
            user = {"_id": new_id("usr"), "email": email, "name": name, "ip_hashes": [], "created_via": m["_id"], "created_at": datetime.now(UTC)}
            if paypal:
                user["payout_details"] = {"method": "paypal", "value": paypal}
            try:
                await db.users.insert_one(user)
            except DuplicateKeyError:
                return await db.users.find_one({"email": email})
        elif paypal and not user.get("payout_details") and user.get("created_via") == m["_id"]:
            await db.users.update_one({"_id": user["_id"]}, {"$set": {"payout_details": {"method": "paypal", "value": paypal}}})
        return user

    async def _claim(self, aff: dict, user: dict):
        """Once per person, and only to accounts this import made that nobody has claimed."""
        db, m = self.db, self.m
        if not self.send_claims or aff["status"] != "approved" or user.get("password_hash") or user.get("created_via") != m["_id"] or user.get("claim_sent_for") == m["_id"]:
            return
        token = random_id(32)
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"claim_token_hash": sha256(token), "claim_sent_for": m["_id"]}})
        await notify.claim_invite(db, m, aff, user, f"{portal_base(m)}/claim?token={token}")

    async def _free_token(self, token: str, aff_id: str | None) -> bool:
        db, mid = self.db, self.m["_id"]
        a = await db.affiliates.find_one({"merchant_id": mid, "token": token}, {"_id": 1})
        if a and a["_id"] != aff_id:
            return False
        link = await db.affiliate_links.find_one({"merchant_id": mid, "token": token}, {"affiliate_id": 1})
        return not link or link["affiliate_id"] == aff_id

    async def _free_code(self, code: str, aff_id: str | None) -> bool:
        db, mid = self.db, self.m["_id"]
        a = await db.affiliates.find_one({"merchant_id": mid, "code": code}, {"_id": 1})
        if a and a["_id"] != aff_id:
            return False
        row = await db.affiliate_codes.find_one({"merchant_id": mid, "code": code}, {"affiliate_id": 1})
        return not row or row["affiliate_id"] == aff_id

    async def affiliates(self):
        db, m = self.db, self.m
        default = await db.campaigns.find_one({"merchant_id": m["_id"], "is_default": True}, {"_id": 1})
        async for rows, total in self.api.pages("/affiliates", [("expand[]", "campaign"), ("expand[]", "links")]):
            for a in rows:
                try:
                    await self._affiliate(a, default["_id"])
                except Exception as e:  # one bad row shouldn't stop thousands of good ones
                    log.exception("rewardful affiliate %s", a.get("id"))
                    self.warn(f"Affiliate {a.get('email')}: skipped ({e}).")
                    continue
                self.counts["affiliates"] += 1
            await self.save("affiliates", total)
        await self.coupons()

    async def _affiliate(self, a: dict, default_campaign: str):
        db, m = self.db, self.m
        email = (a.get("email") or "").strip().lower()
        if "@" not in email:
            self.warn(f"Affiliate {a['id']}: no email address, skipped.")
            return
        name = f"{a.get('first_name') or ''} {a.get('last_name') or ''}".strip() or email.split("@")[0]
        paypal = (a.get("paypal_email") or "").strip() or None
        user = await self._user(email, name, paypal)
        campaign_id = self.campaigns_map.get((a.get("campaign") or {}).get("id")) or default_campaign
        status = "approved" if a.get("state", "active") == "active" else "rejected"
        aff = await db.affiliates.find_one({"merchant_id": m["_id"], "rewardful_id": a["id"]}) or await db.affiliates.find_one({"merchant_id": m["_id"], "user_id": user["_id"]})
        meta = dict((aff or {}).get("metadata") or {})
        if a.get("stripe_customer_id"):
            meta.setdefault("stripe_customer_id", a["stripe_customer_id"])
        tokens = [t for t in dict.fromkeys((l.get("token") or "").strip().lower() for l in a.get("links") or []) if t and len(t) <= 64]
        coupon = a.get("coupon") or {}
        code = (coupon.get("token") or "").strip().upper()[:40] if not coupon.get("archived") else ""
        promo = coupon.get("external_id") if (coupon.get("external_id") or "").startswith("promo_") else None
        fields = {"rewardful_id": a["id"], "campaign_id": campaign_id, "status": status, **({"metadata": meta} if meta else {})}

        if not aff:
            main = next(iter([t for t in tokens if await self._free_token(t, None)]), None) or f"{(slugify(name).replace('-', '') or 'partner')[:16]}{random_id(4).lower()}"
            doc = {"_id": new_id("aff"), "merchant_id": m["_id"], "user_id": user["_id"], **fields, "token": main, "created_at": _time(a.get("created_at")) or datetime.now(UTC)}
            if code and await self._free_code(code, None):
                doc |= {"code": code, **({"stripe_promotion_code_id": promo, "stripe_promotion_code": code} if promo else {})}
            await db.affiliates.insert_one(doc)
            aff = doc
        else:
            await db.affiliates.update_one({"_id": aff["_id"]}, {"$set": fields})
            aff = {**aff, **fields}

        for t in tokens:
            if t == aff["token"] or await db.affiliate_links.find_one({"merchant_id": m["_id"], "token": t, "affiliate_id": aff["_id"]}):
                continue
            if not await self._free_token(t, aff["_id"]):
                self.warn(f"Link ?via={t} ({email}): another affiliate here already uses it, so it wasn't moved.")
                continue
            try:
                await db.affiliate_links.insert_one({"_id": new_id("lnk"), "merchant_id": m["_id"], "affiliate_id": aff["_id"], "token": t, "label": "Rewardful", "created_at": datetime.now(UTC)})
            except DuplicateKeyError:
                pass
        if code and aff.get("code") != code:
            await self._code(aff, code, promo, email)

        self.affiliates_map[a["id"]] = {"id": aff["_id"], "campaign_id": aff["campaign_id"], "user_id": aff["user_id"]}
        await self._claim(aff, user)

    async def _code(self, aff: dict, code: str, promo: str | None, email: str):
        db, m = self.db, self.m
        if await db.affiliate_codes.find_one({"merchant_id": m["_id"], "code": code, "affiliate_id": aff["_id"]}):
            return
        if not await self._free_code(code, aff["_id"]):
            self.warn(f"Code {code} ({email}): another affiliate here already uses it, so it wasn't moved.")
            return
        row = {"_id": new_id("cod"), "merchant_id": m["_id"], "affiliate_id": aff["_id"], "code": code, "created_at": datetime.now(UTC)}
        if promo:
            row["stripe_promotion_code_id"] = promo
        try:
            await db.affiliate_codes.insert_one(row)
        except DuplicateKeyError:
            pass

    async def coupons(self):
        """Affiliates can hold more than the one coupon their record shows."""
        db = self.db
        async for rows, _ in self.api.pages("/affiliate_coupons"):
            for c in rows:
                code = (c.get("token") or "").strip().upper()[:40]
                hit = await self._aff(c.get("affiliate_id"))
                if not code or c.get("archived") or not hit:
                    continue
                aff = await db.affiliates.find_one({"_id": hit["id"]})
                if aff.get("code") != code:
                    promo = c.get("external_id") if (c.get("external_id") or "").startswith("promo_") else None
                    await self._code(aff, code, promo, aff["_id"])
            await self.save("affiliates")

    async def _aff(self, rw_id: str | None) -> dict | None:
        if not rw_id:
            return None
        if rw_id not in self.affiliates_map:
            a = await self.db.affiliates.find_one({"merchant_id": self.m["_id"], "rewardful_id": rw_id}, {"campaign_id": 1, "user_id": 1})
            self.affiliates_map[rw_id] = a and {"id": a["_id"], "campaign_id": a["campaign_id"], "user_id": a["user_id"]}
        return self.affiliates_map[rw_id]

    # Referrals -----------------------------------------------------------------

    async def referrals(self):
        db, m = self.db, self.m
        params = [("conversion_state[]", "lead"), ("conversion_state[]", "conversion")]
        async for rows, total in self.api.pages("/referrals", params):
            for r in rows:
                aff = await self._aff((r.get("affiliate") or {}).get("id"))
                if not aff:
                    continue
                customer = r.get("customer") or {}
                email = (customer.get("email") or "").strip().lower() or None
                cus = r.get("stripe_customer_id") or (customer.get("id") if (customer.get("id") or "").startswith("cus_") else None)
                converted = r.get("conversion_state") == "conversion"
                existing = await db.referrals.find_one({"merchant_id": m["_id"], "rewardful_id": r["id"]})
                if not existing:
                    # Someone Kickrail already tracked keeps the affiliate Kickrail gave them.
                    tracked = await find_referral(db, m["_id"], email, None, cus)
                    if tracked:
                        self.referrals_map[r["id"]] = tracked["_id"]
                        continue
                doc = {
                    "rewardful_id": r["id"],
                    "affiliate_id": aff["id"],
                    "campaign_id": aff["campaign_id"],
                    "source": "rewardful",
                    "status": "customer" if converted else "lead",
                    "first_paid_at": _time(r.get("became_conversion_at")) if converted else None,
                    **({"email": email} if email else {}),
                    **({"stripe_customer_id": cus} if cus else {}),
                }
                if existing:
                    await db.referrals.update_one({"_id": existing["_id"]}, {"$set": doc})
                    self.referrals_map[r["id"]] = existing["_id"]
                else:
                    rid = new_id("ref")
                    await db.referrals.insert_one({"_id": rid, "merchant_id": m["_id"], **doc, "flags": [], "created_at": _time(r.get("created_at")) or datetime.now(UTC)})
                    self.referrals_map[r["id"]] = rid
                self.counts["referrals"] += 1
            await self.save("referrals", total)

    async def _referral(self, rw_id: str | None) -> str | None:
        if not rw_id:
            return None
        if rw_id not in self.referrals_map:
            r = await self.db.referrals.find_one({"merchant_id": self.m["_id"], "rewardful_id": rw_id}, {"_id": 1})
            self.referrals_map[rw_id] = r and r["_id"]
        return self.referrals_map[rw_id]

    # Commissions ---------------------------------------------------------------

    async def commissions(self):
        db, m = self.db, self.m
        now = datetime.now(UTC)
        async for rows, total in self.api.pages("/commissions", [("expand[]", "sale"), ("expand[]", "campaign")]):
            for c in rows:
                sale = c.get("sale") or {}
                aff = await self._aff((sale.get("affiliate") or {}).get("id"))
                if not aff:
                    self.warn(f"Commission {c['id']}: its affiliate wasn't imported, skipped.")
                    continue
                state = c.get("state")
                status = {"paid": "paid", "voided": "void"}.get(state, "pending")
                key = f"rw:{c['id']}"
                existing = await db.commissions.find_one({"merchant_id": m["_id"], "source_key": key}, {"status": 1, "payout_id": 1})
                fields = {
                    "amount_cents": int(c.get("amount") or 0),
                    "currency": (c.get("currency") or "usd").lower(),
                    "status": status,
                    "due_at": _time(c.get("due_at")) or now,
                    **({"paid_at": _time(c.get("paid_at")) or now} if status == "paid" else {}),
                }
                if existing:
                    # Paid out of Kickrail since the last import: Kickrail's record wins.
                    if existing.get("payout_id") and not str(existing["payout_id"]).startswith("rw"):
                        continue
                    await db.commissions.update_one({"_id": existing["_id"]}, {"$set": fields})
                else:
                    referral_id = await self._referral((sale.get("referral") or {}).get("id"))
                    camp = self.campaigns_map.get((c.get("campaign") or {}).get("id")) or aff["campaign_id"]
                    sale_cents = int(sale.get("sale_amount_cents") or 0)
                    doc = {
                        "_id": new_id("com"),
                        "merchant_id": m["_id"],
                        "affiliate_id": aff["id"],
                        "campaign_id": camp,
                        "kind": "sale",
                        "source_key": key,
                        "rewardful_id": c["id"],
                        "base_cents": sale_cents,
                        "original_amount_cents": fields["amount_cents"],
                        "refunded_cents": int(sale.get("refund_amount_cents") or 0),
                        "held": False,
                        **fields,
                        "created_at": _time(c.get("created_at")) or now,
                    }
                    if referral_id:
                        doc["referral_id"] = referral_id
                    if sale.get("stripe_charge_id"):
                        doc["stripe_charge_id"] = sale["stripe_charge_id"]
                    try:
                        await db.commissions.insert_one(doc)
                    except DuplicateKeyError:
                        pass
                self.counts["commissions"] += 1
            await self.save("commissions", total)

    # Payouts -------------------------------------------------------------------

    async def payouts(self):
        """Paid payouts become history. Unpaid ones aren't copied: their commissions stay
        owed and show up on Kickrail's Payouts page."""
        db, m = self.db, self.m
        async for rows, total in self.api.pages("/payouts", [("state", "paid"), ("expand[]", "affiliate"), ("expand[]", "commissions")]):
            for p in rows:
                if p.get("state") != "paid":
                    continue
                aff = await self._aff(p.get("affiliate_id") or (p.get("affiliate") or {}).get("id"))
                if not aff:
                    continue
                keys = [f"rw:{c['id']}" for c in p.get("commissions") or []]
                ids = [c["_id"] async for c in db.commissions.find({"merchant_id": m["_id"], "source_key": {"$in": keys}}, {"_id": 1})]
                pid = f"rw{p['id'].replace('-', '')[:24]}"
                paid_at = _time(p.get("paid_at")) or datetime.now(UTC)
                doc = {
                    "merchant_id": m["_id"],
                    "rewardful_id": p["id"],
                    "currency": (p.get("currency") or "usd").lower(),
                    "method": "manual",
                    "status": "paid",
                    "items": [{"affiliate_id": aff["id"], "user_id": aff["user_id"], "amount_cents": int(p.get("amount") or 0), "commission_ids": ids}],
                    "total_cents": int(p.get("amount") or 0),
                    "fee_cents": 0,
                    "reference": "Paid in Rewardful",
                    "paid_at": paid_at,
                    "created_at": _time(p.get("created_at")) or paid_at,
                }
                await db.payouts.update_one({"_id": pid}, {"$set": doc}, upsert=True)
                if ids:
                    await db.commissions.update_many({"_id": {"$in": ids}, "payout_id": {"$exists": False}}, {"$set": {"payout_id": pid, "status": "paid", "paid_at": paid_at}})
                self.counts["payouts"] += 1
            await self.save("payouts", total)


def import_out(doc: dict | None) -> dict | None:
    if not doc:
        return None
    running = doc["status"] == "running"
    stale = running and (datetime.now(UTC) - doc["heartbeat_at"].replace(tzinfo=UTC)).total_seconds() > STALE_AFTER
    return {
        "id": doc["_id"],
        "source": doc["source"],
        "status": "stopped" if stale else doc["status"],
        "step": doc.get("step"),
        "counts": doc.get("counts") or {},
        "totals": doc.get("totals") or {},
        "warnings": doc.get("warnings") or [],
        "error": doc.get("error"),
        "send_claim_emails": doc.get("send_claim_emails", False),
        "started_at": doc["started_at"],
        "finished_at": doc.get("finished_at"),
    }


async def running_import(db: AsyncDatabase, merchant_id: str) -> dict | None:
    doc = await db.imports.find_one({"merchant_id": merchant_id, "status": "running"}, sort=[("started_at", -1)])
    return doc if doc and (import_out(doc) or {}).get("status") == "running" else None


async def start(db: AsyncDatabase, m: dict, user_id: str, send_claims: bool) -> dict:
    now = datetime.now(UTC)
    doc = {
        "_id": new_id("imp"), "merchant_id": m["_id"], "source": "rewardful", "status": "running", "step": STEPS[0],
        "counts": {}, "totals": {}, "warnings": [], "send_claim_emails": send_claims, "started_by": user_id, "started_at": now, "heartbeat_at": now,
    }
    await db.imports.insert_one(doc)
    return doc


async def run_import(db: AsyncDatabase, m: dict, import_id: str, api, send_claims: bool) -> None:
    run = Run(db, m, import_id, api, send_claims)
    try:
        async with api:
            await run.run()
        done = {"status": "done"}
    except RewardfulError as e:
        done = {"status": "failed", "error": str(e)}
    except Exception:
        log.exception("rewardful import %s", import_id)
        done = {"status": "failed", "error": "something went wrong on our side; running it again picks up where it left off"}
    await db.imports.update_one({"_id": import_id}, {"$set": {**done, "counts": run.counts, "warnings": run.warnings, "finished_at": datetime.now(UTC), "heartbeat_at": datetime.now(UTC)}})
