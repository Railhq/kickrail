"""Keep each imported affiliate's Rewardful visitor total as a starting click count
(affiliates only, nothing else).

    KR_REWARDFUL_SECRET=... .venv/bin/python scripts/backfill_rewardful_visitors.py <slug> [--force]

Uses KR_MONGODB_URI / KR_MONGODB_DB from backend/.env, so point those at the right database.
The secret is read from the environment and never printed. --force replaces counts already set.
"""

import asyncio
import os
import sys

from pymongo import AsyncMongoClient

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import get_settings  # noqa: E402
from app.services.rewardful_import import Rewardful, backfill_visitors  # noqa: E402


async def main(slug: str, force: bool) -> None:
    s = get_settings()
    client = AsyncMongoClient(s.mongodb_uri, tz_aware=True)
    db = client[s.mongodb_db]
    m = await db.merchants.find_one({"slug": slug}, {"_id": 1})
    if not m:
        sys.exit(f"{s.mongodb_db}: no program with slug {slug!r}")
    counts = await backfill_visitors(db, m["_id"], Rewardful(os.environ["KR_REWARDFUL_SECRET"]), force=force)
    print(f"{s.mongodb_db}: {slug} {counts}")
    await client.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    if len(args) != 1 or not os.environ.get("KR_REWARDFUL_SECRET"):
        sys.exit(__doc__)
    asyncio.run(main(args[0], "--force" in sys.argv))
