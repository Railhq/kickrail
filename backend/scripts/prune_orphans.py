"""Remove operators left behind by deleted Railhq accounts who have nothing in Kickrail.

    .venv/bin/python scripts/prune_orphans.py [--subs-file live.txt] [--delete]

Candidates are operators whose railhq_id no longer exists at Railhq accounts, and operators
already unlinked by a user.deleted event (no railhq_id, signed_out_at set). Operators from
before Railhq sign-in (never linked) are only listed. Anyone with a program, team seat or
payout account is kept (services/operators.has_data). Without --delete it only prints.
With --delete it first writes a JSON backup next to this script (chmod 600).

Railhq is asked about each railhq_id (RAILHQ_* settings), or --subs-file gives the live
subs, one per line. Uses KR_MONGODB_URI / KR_MONGODB_DB from backend/.env, so point those
at the right database."""

import argparse
import asyncio
import os
import re
import sys
from datetime import UTC, datetime

from bson import json_util
from pymongo import AsyncMongoClient

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import get_settings  # noqa: E402
from app.railhq import RailhqError  # noqa: E402
from app.routers import railhq  # noqa: E402
from app.services import operators  # noqa: E402

NEVER = re.compile(r"^kqiann@gmail\.com$|@example\.com$")


async def gone_at_railhq(sub: str, live: set[str] | None) -> bool:
    if live is not None:
        return sub not in live
    try:
        await railhq.client().user(sub)
        return False
    except RailhqError as e:
        if e.status == 404:
            return True
        raise


async def main(subs_file: str | None, delete: bool) -> None:
    s = get_settings()
    live = {x.strip() for x in open(subs_file) if x.strip()} if subs_file else None
    client = AsyncMongoClient(s.mongodb_uri, tz_aware=True)
    db = client[s.mongodb_db]
    doomed: list[dict] = []
    async for u in db.users.find({}):
        email = u.get("email", "")
        if NEVER.search(email):
            continue
        sub = u.get("railhq_id")
        if sub:
            orphan = await gone_at_railhq(sub, live)
        else:
            orphan = bool(u.get("signed_out_at"))
            if not orphan and not await operators.has_data(db, u):
                print(f"skip    {u['_id']} {email} (from before Railhq, never linked)")
        if not orphan:
            continue
        if await operators.has_data(db, u):
            print(f"keep    {u['_id']} {email} (has programs or a payout account)")
            continue
        print(f"remove  {u['_id']} {email} {u.get('name', '')!r} created {u.get('created_at')}")
        doomed.append(u)
    print(f"{s.mongodb_db}: {len(doomed)} to remove")
    if delete and doomed:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"prune-backup-{datetime.now(UTC):%Y%m%d%H%M%S}.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json_util.dumps(doomed))
        print(f"backup  {path}")
        gone = sum([await operators.remove_if_empty(db, u) for u in doomed])
        print(f"removed {gone}")
    await client.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--subs-file")
    p.add_argument("--delete", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.subs_file, a.delete))
