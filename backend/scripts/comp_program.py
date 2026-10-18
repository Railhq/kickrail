"""Put a program on Kickrail for free (Scale features, no revenue cap, no billing).

    .venv/bin/python scripts/comp_program.py <slug> [--off]

Uses KR_MONGODB_URI / KR_MONGODB_DB from backend/.env, so point those at the right database.
"""

import asyncio
import sys

from pymongo import AsyncMongoClient

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from app.config import get_settings  # noqa: E402


async def main(slug: str, on: bool) -> None:
    s = get_settings()
    client = AsyncMongoClient(s.mongodb_uri, tz_aware=True)
    res = await client[s.mongodb_db].merchants.update_one({"slug": slug}, {"$set": {"comped": True}} if on else {"$unset": {"comped": ""}})
    print(f"{s.mongodb_db}: {slug} {'comped' if on else 'no longer comped'}" if res.matched_count else f"{s.mongodb_db}: no program with slug {slug!r}")
    await client.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], "--off" not in sys.argv))
