"""Add the Rewardful link to a program's imported referrals (referrals only, nothing else).

    KR_REWARDFUL_SECRET=... .venv/bin/python scripts/backfill_rewardful_links.py <slug>

Uses KR_MONGODB_URI / KR_MONGODB_DB from backend/.env, so point those at the right database.
The secret is read from the environment and never printed.
"""

import asyncio
import os
import sys

from pymongo import AsyncMongoClient

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import get_settings  # noqa: E402
from app.services.rewardful_import import Rewardful, backfill_links  # noqa: E402


async def main(slug: str) -> None:
    s = get_settings()
    client = AsyncMongoClient(s.mongodb_uri, tz_aware=True)
    db = client[s.mongodb_db]
    m = await db.merchants.find_one({"slug": slug}, {"_id": 1})
    if not m:
        sys.exit(f"{s.mongodb_db}: no program with slug {slug!r}")
    counts = await backfill_links(db, m["_id"], Rewardful(os.environ["KR_REWARDFUL_SECRET"]))
    print(f"{s.mongodb_db}: {slug} {counts}")
    await client.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or not os.environ.get("KR_REWARDFUL_SECRET"):
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
