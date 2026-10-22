"""Daily exchange rates, so a program paid in several currencies can show one approximate total.

Display only: commissions and payouts stay in the currency of the sale. Rates are the
European Central Bank's daily reference rates via frankfurter.dev (free, no key), fetched
at most once a day and kept in Mongo so a failed fetch falls back to the last good day.
"""

from datetime import UTC, datetime

import httpx

URL = "https://api.frankfurter.dev/v1/latest"
# The settings page offers these; all are in the ECB set.
DISPLAY_CURRENCIES = ["usd", "eur", "gbp", "cad", "aud", "inr", "jpy", "sgd", "chf", "nzd", "sek", "brl", "mxn"]

_cache: dict = {}


async def _fetch() -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(URL, params={"base": "EUR"})
        r.raise_for_status()
        body = r.json()
        return {"date": body["date"], "rates": {"eur": 1.0} | {k.lower(): float(v) for k, v in body["rates"].items()}}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


async def _rates(db) -> dict | None:
    """Euro-based rates, refreshed once per UTC day."""
    today = datetime.now(UTC).date().isoformat()
    if _cache.get("checked_on") == today:
        return _cache.get("rates")
    doc = await db.fx_rates.find_one({}, sort=[("_id", -1)])
    if not doc or doc.get("checked_on") != today:
        if fresh := await fetch():
            doc = {"_id": fresh["date"], "rates": fresh["rates"], "checked_on": today}
            await db.fx_rates.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    _cache.update(checked_on=today, rates=doc)
    return doc


async def for_display(db, currency: str) -> dict | None:
    """{currency, date, per_unit}: per_unit[c] is how much one unit of c is worth in `currency`.
    None when no rates are available, and the UI then shows exact amounts only."""
    doc = await _rates(db)
    if not doc or currency not in doc["rates"]:
        return None
    base = doc["rates"][currency]
    return {"currency": currency, "date": doc["_id"], "per_unit": {c: base / v for c, v in doc["rates"].items()}}


# Swapped out in tests.
fetch = _fetch
