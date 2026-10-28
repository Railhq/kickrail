"""Move affiliates out of `users` into their own `partners` collection.

    .venv/bin/python scripts/migrate_partners.py                    dry run: counts and a sample, writes nothing
    .venv/bin/python scripts/migrate_partners.py --apply            copy (safe to run again, and to resume)
    .venv/bin/python scripts/migrate_partners.py --cleanup          dry run of the cleanup
    .venv/bin/python scripts/migrate_partners.py --cleanup --apply  remove what the copy made redundant

Uses KR_MONGODB_URI / KR_MONGODB_DB (env, else backend/.env). Refuses anything but a local
Mongo unless --allow-remote is given.

The copy:
- finds every users record that belongs to an affiliate: the user_id of an affiliates row,
  or one with affiliate-only data (payout details, a Stripe Connect account, a tax form, an
  unclaimed account a program made, or an email confirmation that was going to /join or /a);
- copies each, whole and under the SAME _id, to partners. affiliates.user_id and payout
  items' user_id already point at those ids, so referral links, codes, commissions and
  payouts don't change. Password hashes and session_gen are copied as is, so passwords and
  existing sessions keep working;
- saves the untouched users record to users_premigration_backup first;
- never changes or deletes a users record.
Run again after the new code is live to pick up anything the old code wrote in between: a
partner copy is refreshed only while the partner record itself hasn't changed since it was
copied; if both changed, it is listed as a conflict and left alone.

The cleanup (a separate run, after the copy has been checked):
- deletes the users records that only ever belonged to an affiliate (no program team);
- strips the affiliate-only fields from people who run a program too;
each only when the partner copy and the backup both exist.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pymongo import AsyncMongoClient, ReplaceOne
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import get_settings  # noqa: E402

NAME = "partners_split_v1"
BACKUP = "users_premigration_backup"
# Fields only an affiliate has. Cleanup strips these from people who also run a program.
PARTNER_FIELDS = ("payout_details", "connect_account_id", "payouts_enabled", "tax_info", "claim_token_hash", "created_via", "claim_sent_for", "claimed_at")
# Not compared when deciding whether a record changed: every sign-in appends one.
VOLATILE = ("ip_hashes", "_migration")
BATCH = 500


def _hash(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k not in VOLATILE}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _is_local(uri: str) -> bool:
    hosts = (urlsplit(uri).netloc.rsplit("@", 1)[-1]).split(",")
    return all(h.split(":")[0] in ("127.0.0.1", "localhost", "::1", "[::1]") for h in hosts)


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


async def candidates(db) -> tuple[set, set]:
    """(ids that belong to an affiliate, ids that are on a program's team)."""
    ids = set(await db.affiliates.distinct("user_id"))
    marker = {"$or": [{f: {"$exists": True}} for f in ("payout_details", "connect_account_id", "tax_info", "claim_token_hash", "created_via", "claim_sent_for")] + [{"verify_next": {"$regex": "^/(join|a)(/|$)"}}]}
    ids |= {u["_id"] async for u in db.users.find(marker, {"_id": 1})}
    members = set()
    async for m in db.merchants.find({}, {"member_ids": 1, "owner_id": 1}):
        members |= set(m.get("member_ids") or [])
        if m.get("owner_id"):
            members.add(m["owner_id"])
    return ids, members


async def copy(db, apply: bool) -> dict:
    ids, members = await candidates(db)
    now = datetime.now(UTC)
    c = {"affiliate_user_ids": len(ids), "missing_users": 0, "partner_only": 0, "also_operators": 0, "to_insert": 0, "to_refresh": 0, "up_to_date": 0, "conflicts": 0, "email_taken_in_partners": 0, "backed_up": 0}
    samples, conflicts = [], []
    todo = sorted(ids)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i : i + BATCH]
        users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": chunk}})}
        partners = {p["_id"]: p async for p in db.partners.find({"_id": {"$in": chunk}})}
        backups = {b["_id"] async for b in db[BACKUP].find({"_id": {"$in": chunk}}, {"_id": 1})}
        inserts, refreshes, backup_docs = [], [], []
        for uid in chunk:
            u = users.get(uid)
            if not u:
                c["missing_users"] += 1  # an affiliates row whose person is already gone
                continue
            c["also_operators" if uid in members else "partner_only"] += 1
            if uid not in backups:
                backup_docs.append(u | {"_backed_up_at": now})
            src = _hash(u)
            p = partners.get(uid)
            doc = u | {"_migration": {"name": NAME, "source_hash": src, "copy_hash": src, "at": now}}
            if not p:
                inserts.append(doc)
                if len(samples) < 5:
                    samples.append({"_id": uid, "email": _mask(u["email"]), "role": "also operator" if uid in members else "partner only", "has_password": bool(u.get("password_hash")), "affiliates": None})
                continue
            mig = p.get("_migration") or {}
            if mig.get("source_hash") == src:
                c["up_to_date"] += 1
            elif mig.get("copy_hash") == _hash(p):
                # The users record changed (old code still running) and the partner didn't: copy again.
                # Keep the partner's own sign-in IPs: new code appends them there.
                doc["ip_hashes"] = list(dict.fromkeys((u.get("ip_hashes") or []) + (p.get("ip_hashes") or [])))[-10:]
                refreshes.append(ReplaceOne({"_id": uid, "_migration.copy_hash": mig["copy_hash"]}, doc))
            else:
                c["conflicts"] += 1
                conflicts.append({"_id": uid, "email": _mask(u["email"])})
        c["to_insert"] += len(inserts)
        c["to_refresh"] += len(refreshes)
        c["backed_up"] += len(backup_docs)
        if apply:
            if backup_docs:
                try:
                    await db[BACKUP].insert_many(backup_docs, ordered=False)
                except Exception as e:  # noqa: BLE001  a resumed run: some are already there
                    if "E11000" not in str(e):
                        raise
            for d in inserts:
                try:
                    await db.partners.insert_one(d)
                except DuplicateKeyError as e:
                    if "email" in str(e):
                        # A partner with this email signed up under the new code in between.
                        c["email_taken_in_partners"] += 1
                        conflicts.append({"_id": d["_id"], "email": _mask(d["email"]), "why": "email already in partners"})
                    # else: same _id inserted by a parallel run; fine.
            if refreshes:
                await db.partners.bulk_write(refreshes, ordered=False)
    for s in samples:
        s["affiliates"] = await db.affiliates.count_documents({"user_id": s["_id"]})
    return {"counts": c, "sample": samples, "conflicts": conflicts[:50]}


async def cleanup(db, apply: bool) -> dict:
    ids, members = await candidates(db)
    c = {"delete_partner_only_users": 0, "strip_fields_from_operators": 0, "skipped_no_partner_or_backup": 0, "already_clean": 0}
    todo = sorted(ids)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i : i + BATCH]
        users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": chunk}})}
        ok = {p["_id"] async for p in db.partners.find({"_id": {"$in": chunk}}, {"_id": 1})} & {b["_id"] async for b in db[BACKUP].find({"_id": {"$in": chunk}}, {"_id": 1})}
        for uid in chunk:
            u = users.get(uid)
            if not u:
                c["already_clean"] += 1
                continue
            if uid not in ok:
                c["skipped_no_partner_or_backup"] += 1
                continue
            if uid in members:
                if not any(f in u for f in PARTNER_FIELDS):
                    c["already_clean"] += 1
                    continue
                c["strip_fields_from_operators"] += 1
                if apply:
                    await db.users.update_one({"_id": uid}, {"$unset": {f: "" for f in PARTNER_FIELDS}})
            else:
                c["delete_partner_only_users"] += 1
                if apply:
                    # Checked again at delete time: someone could have joined a team since.
                    if not await db.merchants.find_one({"$or": [{"member_ids": uid}, {"owner_id": uid}]}, {"_id": 1}):
                        await db.users.delete_one({"_id": uid})
    return {"counts": c}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write (without it nothing is written)")
    ap.add_argument("--cleanup", action="store_true", help="the second step, after the copy is checked")
    ap.add_argument("--allow-remote", action="store_true", help="allow a Mongo that isn't on this machine")
    a = ap.parse_args()
    s = get_settings()
    uri = os.environ.get("KR_MONGODB_URI", s.mongodb_uri)
    if not _is_local(uri) and not a.allow_remote:
        sys.exit("refusing: KR_MONGODB_URI is not a local Mongo (pass --allow-remote once this is approved)")
    client = AsyncMongoClient(uri, tz_aware=True)
    db = client[s.mongodb_db]
    mode = ("cleanup" if a.cleanup else "copy") + ("" if a.apply else " (dry run, nothing written)")
    print(f"{s.mongodb_db} on {urlsplit(uri).netloc.rsplit('@', 1)[-1]}: {mode}")
    if a.cleanup:
        if not await db.migrations.find_one({"_id": NAME, "copied_at": {"$exists": True}}):
            sys.exit("refusing: run the copy with --apply first")
        out = await cleanup(db, a.apply)
    else:
        if a.apply:
            await db.partners.create_index("email", unique=True)
        out = await copy(db, a.apply)
    if a.apply:
        now = datetime.now(UTC)
        key = "cleaned_at" if a.cleanup else "copied_at"
        await db.migrations.update_one({"_id": NAME}, {"$set": {key: now}, "$push": {"runs": {"at": now, "step": "cleanup" if a.cleanup else "copy", "counts": out["counts"]}}}, upsert=True)
    print(json.dumps(out, indent=1, default=str))
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
