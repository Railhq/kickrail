"""Payout batches.

Stripe method: the merchant funds one Checkout payment on the Kickrail platform
for the batch total, then each affiliate gets a Connect transfer sourced from
that charge. Manual method: the merchant pays outside Kickrail (PayPal, Wise,
bank) using the details each affiliate saved, then marks those affiliates paid.
A manual batch can be undone if it was recorded by mistake. PayPal method: one
PayPal Payouts batch from the merchant's own PayPal account to every affiliate
who saved a PayPal email; item results are polled until each one settles.

With settings.require_tax_form, affiliates without a W-9/W-8 on file are listed
but left out of every batch until they submit one.

Commissions in a batch are reserved with payout_id so they can't be paid twice;
a failed transfer releases its commissions back into the payable pool.

payout.due tells the merchant's server that an affiliate's balance became
payable, once per commission, so programs that reward in kind (a discount, a
credit) can grant it and then record a manual payout over the API.
"""

import csv
import io
import logging
from datetime import UTC, datetime
from functools import partial

from pymongo.asynchronous.database import AsyncDatabase

from ..config import get_settings
from ..db import run_in_transaction
from ..domain.commission import payable_lines
from ..ids import new_id
from . import audit, notify
from .outbox import emit
from .paypal import DONE_FAILED, DONE_OK
from .stripe_api import PlatformApi

log = logging.getLogger(__name__)


def paypal_email(details: dict | None) -> str | None:
    if details and details.get("method") == "paypal" and "@" in details.get("value", ""):
        return details["value"].strip()
    return None


async def payable(db: AsyncDatabase, merchant_id: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    merchant = await db.merchants.find_one({"_id": merchant_id}, {"settings": 1}) or {}
    require_tax = (merchant.get("settings") or {}).get("require_tax_form", False)
    commissions = await db.commissions.find({"merchant_id": merchant_id, "status": "pending", "payout_id": {"$exists": False}}).to_list(None)
    affiliates = {a["_id"]: a async for a in db.affiliates.find({"merchant_id": merchant_id})}
    campaigns = {c["_id"]: c async for c in db.campaigns.find({"merchant_id": merchant_id})}
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [a["user_id"] for a in affiliates.values()]}})}

    def min_payout(aff_id: str) -> int:
        aff = affiliates.get(aff_id)
        camp = campaigns.get(aff["campaign_id"]) if aff else None
        return camp.get("min_payout_cents", 0) if camp else 0

    out = []
    for line in payable_lines(commissions, now, min_payout):
        aff = affiliates[line.affiliate_id]
        user = users.get(aff["user_id"], {})
        out.append(
            {
                "affiliate_id": line.affiliate_id,
                "user_id": aff["user_id"],
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "currency": line.currency,
                "amount_cents": line.amount_cents,
                "commission_ids": line.commission_ids,
                "payouts_enabled": bool(user.get("payouts_enabled")),
                "payout_details": user.get("payout_details"),
                "paypal_email": paypal_email(user.get("payout_details")),
                "tax_form": (user.get("tax_info") or {}).get("form"),
                "needs_tax_form": require_tax and not user.get("tax_info"),
            }
        )
    return out


async def create_payout(
    db: AsyncDatabase, merchant: dict, currency: str, method: str, platform: PlatformApi | None,
    affiliate_ids: list[str] | None = None, reference: str = "", paypal=None,
) -> dict:
    lines = [l for l in await payable(db, merchant["_id"]) if l["currency"] == currency and not l["needs_tax_form"]]
    if method == "stripe":
        lines = [l for l in lines if l["payouts_enabled"]]
    if method == "paypal":
        lines = [l for l in lines if l["paypal_email"]]
    if affiliate_ids is not None:
        lines = [l for l in lines if l["affiliate_id"] in set(affiliate_ids)]
    if not lines:
        raise ValueError("nothing payable" + {"stripe": " to affiliates with Stripe payouts set up", "paypal": " to affiliates with a PayPal email saved", "manual": ""}[method])

    payout_id = new_id("po")
    total = sum(l["amount_cents"] for l in lines)
    fee = round(total * get_settings().payout_fee_bps / 10_000) if method == "stripe" else 0
    payout = {
        "_id": payout_id,
        "merchant_id": merchant["_id"],
        "currency": currency,
        "method": method,
        "status": {"stripe": "awaiting_funding", "manual": "paid", "paypal": "processing"}[method],
        "items": [{"affiliate_id": l["affiliate_id"], "user_id": l["user_id"], "amount_cents": l["amount_cents"], "commission_ids": l["commission_ids"]} for l in lines],
        "total_cents": total,
        "fee_cents": fee,
        "created_at": datetime.now(UTC),
    }
    if reference:
        payout["reference"] = reference
    all_ids = [cid for l in lines for cid in l["commission_ids"]]
    # Reserve only commissions still unreserved; bail if another batch grabbed any.
    res = await db.commissions.update_many({"_id": {"$in": all_ids}, "payout_id": {"$exists": False}, "status": "pending"}, {"$set": {"payout_id": payout_id}})
    if res.modified_count != len(all_ids):
        await db.commissions.update_many({"payout_id": payout_id}, {"$unset": {"payout_id": ""}})
        raise ValueError("commissions changed while building the payout; try again")

    if method == "manual":
        now = datetime.now(UTC)
        payout["paid_at"] = now

        async def paid(tdb):
            await tdb.payouts.insert_one(payout)
            await tdb.commissions.update_many({"payout_id": payout_id}, {"$set": {"status": "paid", "paid_at": now}})
            await notify.payout_paid(tdb, merchant, payout)
            await audit.record(tdb, merchant["_id"], "payout.created", payout_id, **audit.payout_detail(payout))

        await run_in_transaction(db, paid)
        return payout

    if method == "paypal":
        assert paypal is not None
        emails = {l["affiliate_id"]: l["paypal_email"] for l in lines}
        for item in payout["items"]:
            item |= {"sender_item_id": f"{payout_id}:{item['affiliate_id']}", "paypal_email": emails[item["affiliate_id"]], "status": "pending"}
        try:
            batch_id = await paypal.create_batch(
                payout_id, f"You have a payout from {merchant['name']}",
                [{"email": i["paypal_email"], "amount_cents": i["amount_cents"], "currency": currency, "sender_item_id": i["sender_item_id"], "note": reference or f"{merchant['name']} affiliate commissions"} for i in payout["items"]],
            )
        except Exception:
            await db.commissions.update_many({"payout_id": payout_id}, {"$unset": {"payout_id": ""}})
            raise
        payout["paypal_batch_id"] = batch_id
        await _save_new(db, merchant, payout)
        return payout

    assert platform is not None
    base = get_settings().public_url
    try:
        session_id, url = await platform.funding_checkout(
            payout_id, total + fee, currency, f"Kickrail affiliate payout ({len(lines)} affiliates)",
            f"{base}/dashboard/payouts?funded={payout_id}", f"{base}/dashboard/payouts?cancelled={payout_id}",
        )
    except Exception:
        await db.commissions.update_many({"payout_id": payout_id}, {"$unset": {"payout_id": ""}})
        raise
    payout["funding_session_id"] = session_id
    payout["funding_url"] = url
    await _save_new(db, merchant, payout)
    return payout


async def _save_new(db: AsyncDatabase, merchant: dict, payout: dict) -> None:
    async def save(tdb):
        await tdb.payouts.insert_one(payout)
        await audit.record(tdb, merchant["_id"], "payout.created", payout["_id"], **audit.payout_detail(payout))

    await run_in_transaction(db, save)


async def undo_manual_payout(db: AsyncDatabase, merchant_id: str, payout_id: str) -> bool:
    """For a batch marked paid by mistake: its commissions go back to payable."""
    async def undo(tdb) -> bool:
        res = await tdb.payouts.update_one(
            {"_id": payout_id, "merchant_id": merchant_id, "method": "manual", "status": "paid"}, {"$set": {"status": "undone", "undone_at": datetime.now(UTC)}}
        )
        if res.modified_count:
            await tdb.commissions.update_many({"payout_id": payout_id, "status": "paid"}, {"$set": {"status": "pending"}, "$unset": {"payout_id": "", "paid_at": ""}})
            await notify.payout_event(tdb, merchant_id, "payout.undone", payout_id)
            await audit.record(tdb, merchant_id, "payout.undone", payout_id)
        return bool(res.modified_count)

    return await run_in_transaction(db, undo)


async def cancel_payout(db: AsyncDatabase, merchant_id: str, payout_id: str) -> bool:
    async def cancel(tdb) -> bool:
        res = await tdb.payouts.update_one({"_id": payout_id, "merchant_id": merchant_id, "status": "awaiting_funding"}, {"$set": {"status": "cancelled"}})
        if res.modified_count:
            await tdb.commissions.update_many({"payout_id": payout_id, "status": "pending"}, {"$unset": {"payout_id": ""}})
            await audit.record(tdb, merchant_id, "payout.cancelled", payout_id)
        return bool(res.modified_count)

    return await run_in_transaction(db, cancel)


async def complete_funded_payout(db: AsyncDatabase, payout_id: str, session_id: str, platform: PlatformApi) -> str:
    # Claim the batch so a webhook retry can't run the transfers twice.
    payout = await db.payouts.find_one_and_update(
        {"_id": payout_id, "funding_session_id": session_id, "status": "awaiting_funding"}, {"$set": {"status": "processing"}}
    )
    if not payout:
        return "not awaiting funding"
    charge_id = await platform.charge_for_session(session_id)
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [i["user_id"] for i in payout["items"]]}})}
    items, failures, now = [], 0, datetime.now(UTC)
    for item in payout["items"]:
        user = users.get(item["user_id"], {})
        try:
            transfer_id = await platform.transfer(
                item["amount_cents"], payout["currency"], user["connect_account_id"], charge_id, payout_id, f"{payout_id}:{item['affiliate_id']}"
            )
            await db.commissions.update_many({"_id": {"$in": item["commission_ids"]}}, {"$set": {"status": "paid", "paid_at": now}})
            items.append({**item, "transfer_id": transfer_id})
        except Exception as e:
            log.exception("transfer failed for %s in %s", item["affiliate_id"], payout_id)
            failures += 1
            await db.commissions.update_many({"_id": {"$in": item["commission_ids"]}}, {"$unset": {"payout_id": ""}})
            items.append({**item, "error": str(e)[:300]})
    status = "paid" if failures == 0 else ("failed" if failures == len(items) else "partial")

    async def settle(tdb):
        await tdb.payouts.update_one({"_id": payout_id}, {"$set": {"items": items, "status": status, "funding_charge_id": charge_id, "paid_at": now}})
        merchant = await tdb.merchants.find_one({"_id": payout["merchant_id"]})
        done = await tdb.payouts.find_one({"_id": payout_id})
        if status == "failed":
            await notify.payout_event(tdb, payout["merchant_id"], "payout.failed", payout_id)
        elif merchant and done:
            await notify.payout_paid(tdb, merchant, done, [i for i in items if not i.get("error")])

    await run_in_transaction(db, settle)
    return f"payout {status}"


async def sync_paypal_payout(db: AsyncDatabase, payout: dict, paypal) -> str:
    """Apply PayPal's item results. Paid items mark their commissions paid; failed
    or returned ones go back into the payable pool. Safe to call repeatedly."""
    batch = await paypal.batch(payout["paypal_batch_id"])

    async def apply(tdb) -> str:
        by_item = {i["sender_item_id"]: i for i in batch["items"]}
        merchant = await tdb.merchants.find_one({"_id": payout["merchant_id"]})
        now, newly_paid, items = datetime.now(UTC), [], []
        for item in payout["items"]:
            remote = by_item.get(item["sender_item_id"])
            if remote and item.get("status") == "pending":
                if remote["status"] in DONE_OK:
                    await tdb.commissions.update_many({"_id": {"$in": item["commission_ids"]}}, {"$set": {"status": "paid", "paid_at": now}})
                    item = {**item, "status": "paid", "paypal_item_id": remote["item_id"]}
                    newly_paid.append(item)
                elif remote["status"] in DONE_FAILED:
                    await tdb.commissions.update_many({"_id": {"$in": item["commission_ids"]}}, {"$unset": {"payout_id": ""}})
                    item = {**item, "status": "failed", "error": remote["error"] or remote["status"].lower()}
                else:
                    item = {**item, "paypal_state": remote["status"]}
            items.append(item)
        statuses = {i["status"] for i in items}
        s: dict = {"items": items, "paypal_status": batch["status"], "checked_at": now}
        if "pending" not in statuses:
            s["status"] = "paid" if statuses == {"paid"} else "failed" if statuses == {"failed"} else "partial"
            s["paid_at"] = now
        await tdb.payouts.update_one({"_id": payout["_id"]}, {"$set": s})
        done = await tdb.payouts.find_one({"_id": payout["_id"]})
        # Emails go out per affiliate as PayPal confirms them; the event once the batch settles.
        if merchant and newly_paid:
            await notify.payout_paid(tdb, merchant, done, newly_paid, event=False)
        if s.get("status") == "failed":
            await notify.payout_event(tdb, payout["merchant_id"], "payout.failed", payout["_id"])
        elif s.get("status"):
            await notify.payout_event(tdb, payout["merchant_id"], "payout.paid", payout["_id"])
        return s.get("status", "processing")

    return await run_in_transaction(db, apply)


async def announce_due(db: AsyncDatabase, now: datetime | None = None) -> int:
    """Emit payout.due for every affiliate balance holding a commission that hasn't
    been announced yet. Returns how many events went out."""
    now = now or datetime.now(UTC)
    fresh = {"status": "pending", "due_at": {"$lte": now}, "held": {"$ne": True}, "payout_id": {"$exists": False}, "due_announced_at": {"$exists": False}}
    sent = 0
    for merchant_id in await db.commissions.distinct("merchant_id", fresh):
        for line in await payable(db, merchant_id, now):
            ids = line["commission_ids"]
            new = await db.commissions.find({"_id": {"$in": ids}, "due_announced_at": {"$exists": False}}, {"amount_cents": 1}).to_list(None)
            if not new:
                continue
            # A clawback landing on a balance already announced lowers it; that isn't news.
            news = any(c["amount_cents"] > 0 for c in new)
            await run_in_transaction(db, partial(_announce, merchant_id=merchant_id, line=line, ids=ids, new=new, now=now, news=news))
            sent += news
    return sent


async def _announce(tdb, *, merchant_id: str, line: dict, ids: list[str], new: list[dict], now: datetime, news: bool) -> None:
    await tdb.commissions.update_many({"_id": {"$in": [c["_id"] for c in new]}}, {"$set": {"due_announced_at": now}})
    if news:
        aff = await tdb.affiliates.find_one({"_id": line["affiliate_id"]}, {"campaign_id": 1, "metadata": 1})
        await emit(
            tdb, merchant_id, "payout.due",
            {
                "object": "payout_due",
                "affiliate_id": line["affiliate_id"],
                "campaign_id": aff["campaign_id"],
                "email": line["email"],
                "name": line["name"],
                "metadata": aff.get("metadata"),
                "currency": line["currency"],
                "amount_cents": line["amount_cents"],
                "commission_ids": ids,
                "needs_tax_form": line["needs_tax_form"],
            },
        )


async def poll_paypal(db: AsyncDatabase, factory) -> None:
    async for payout in db.payouts.find({"method": "paypal", "status": "processing"}):
        merchant = await db.merchants.find_one({"_id": payout["merchant_id"]})
        if not merchant or not merchant.get("paypal"):
            continue
        try:
            await sync_paypal_payout(db, payout, factory(merchant))
        except Exception:
            log.warning("PayPal sync failed for %s", payout["_id"], exc_info=True)


def _details(u: dict) -> tuple[str, str]:
    d = u.get("payout_details") or {}
    return d.get("method", ""), d.get("value", "")


def payout_csv(payout: dict, users: dict[str, dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "payout_method", "payout_details", "amount", "currency", "commissions", "transfer_id"])
    for i in payout["items"]:
        u = users.get(i["user_id"], {})
        w.writerow([u.get("name", ""), u.get("email", ""), *_details(u), f"{i['amount_cents'] / 100:.2f}", payout["currency"].upper(), len(i["commission_ids"]), i.get("transfer_id", "")])
    return buf.getvalue()


def paypal_csv(lines: list[dict], note: str) -> str:
    """PayPal's bulk payout upload format: email, amount, currency, reference id,
    note, one row per recipient and no header. Upload it under PayPal > Pay & get
    paid > Payouts, then mark the same affiliates paid here."""
    buf = io.StringIO()
    w = csv.writer(buf)
    for l in lines:
        if l.get("paypal_email"):
            w.writerow([l["paypal_email"], f"{l['amount_cents'] / 100:.2f}", l["currency"].upper(), l["affiliate_id"], note])
    return buf.getvalue()


def due_csv(lines: list[dict]) -> str:
    """What's owed right now, to pay from before marking anyone paid."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "payout_method", "payout_details", "amount", "currency", "commissions"])
    for l in lines:
        w.writerow([l["name"], l["email"], *_details(l), f"{l['amount_cents'] / 100:.2f}", l["currency"].upper(), len(l["commission_ids"])])
    return buf.getvalue()
