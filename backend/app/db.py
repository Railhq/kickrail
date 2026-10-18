from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, TypeVar

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from .config import get_settings

_client: AsyncMongoClient | None = None
_db: AsyncDatabase | None = None


async def get_db() -> AsyncDatabase:
    global _client, _db
    if _db is None:
        s = get_settings()
        _client = AsyncMongoClient(s.mongodb_uri, tz_aware=True)
        _db = _client[s.mongodb_db]
        await ensure_indexes(_db)
    return _db


class _InSession:
    """A database handle whose collection calls all join one session, so code written
    against a plain database (notify, the outbox) runs inside the caller's transaction."""

    def __init__(self, db: AsyncDatabase, session):
        self._db, self._session = db, session

    def __getattr__(self, name: str):
        return _CollectionInSession(self._db[name], self._session)

    __getitem__ = __getattr__


class _CollectionInSession:
    def __init__(self, coll, session):
        self._coll, self._session = coll, session

    def __getattr__(self, name: str):
        attr = getattr(self._coll, name)
        return partial(attr, session=self._session) if callable(attr) else attr


_transactions: bool | None = None
T = TypeVar("T")


async def run_in_transaction(db: Any, fn: Callable[[Any], Awaitable[T]]) -> T:
    """Run `fn(db)` so its writes, and the outbox rows it queues, commit together or not
    at all. Retried on transient conflicts, so `fn` must be safe to run again and must not
    call outside services. A unique-key error aborts the transaction and is raised to the
    caller. On a standalone server (local dev) `fn` runs without a transaction."""
    global _transactions
    if isinstance(db, _InSession):
        return await fn(db)  # already inside one
    if _transactions is None:
        hello = await db.command("hello")
        _transactions = bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"
    if not _transactions:
        result = await fn(db)
    else:
        async with db.client.start_session() as s:
            result = await s.with_transaction(lambda s: fn(_InSession(db, s)))
    from .services.outbox import wake

    wake()  # the dispatcher can see the new rows only once they commit
    return result


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        await _client.close()
    _client, _db = None, None


async def ensure_indexes(db: AsyncDatabase) -> None:
    A, D = ASCENDING, DESCENDING
    specs = {
        "users": [([("email", A)], {"unique": True}), ([("connect_account_id", A)], {"sparse": True})],
        "merchants": [
            ([("slug", A)], {"unique": True}),
            ([("public_key", A)], {"unique": True}),
            ([("secret_key_hash", A)], {"unique": True}),
            ([("member_ids", A)], {}),
            ([("stripe.account_id", A)], {"sparse": True}),
            ([("portal_domains.host", A)], {"unique": True, "partialFilterExpression": {"portal_domains.host": {"$type": "string"}}}),
        ],
        "campaigns": [([("merchant_id", A)], {}), ([("merchant_id", A), ("slug", A)], {"unique": True, "partialFilterExpression": {"slug": {"$type": "string"}}})],
        "affiliates": [
            ([("merchant_id", A), ("token", A)], {"unique": True}),
            ([("merchant_id", A), ("code", A)], {"unique": True, "partialFilterExpression": {"code": {"$type": "string"}}}),
            ([("merchant_id", A), ("user_id", A)], {"unique": True}),
            ([("merchant_id", A), ("stripe_promotion_code_id", A)], {"sparse": True}),
            ([("user_id", A)], {}),
        ],
        "clicks": [([("merchant_id", A), ("affiliate_id", A), ("created_at", D)], {})],
        # One referral per person per program, however many requests report them at once.
        "referrals": [
            ([("merchant_id", A), ("stripe_customer_id", A)], {"unique": True, "partialFilterExpression": {"stripe_customer_id": {"$type": "string"}}}),
            ([("merchant_id", A), ("email", A)], {"unique": True, "partialFilterExpression": {"email": {"$type": "string"}}}),
            ([("merchant_id", A), ("external_user_id", A)], {"unique": True, "partialFilterExpression": {"external_user_id": {"$type": "string"}}}),
            ([("merchant_id", A), ("affiliate_id", A), ("created_at", D)], {}),
            # Waiting to be written onto the Stripe customer (services/stripe_sync.py).
            ([("stripe_sync_due", A)], {"partialFilterExpression": {"stripe_sync_due": True}}),
        ],
        "commissions": [
            ([("merchant_id", A), ("source_key", A)], {"unique": True}),
            ([("merchant_id", A), ("status", A), ("due_at", A)], {}),
            ([("merchant_id", A), ("payment_intent_id", A)], {"sparse": True}),
            ([("affiliate_id", A), ("created_at", D)], {}),
            # payout.due sweep, across programs.
            ([("status", A), ("due_at", A)], {"partialFilterExpression": {"status": "pending"}}),
        ],
        "payouts": [([("merchant_id", A), ("created_at", D)], {}), ([("funding_session_id", A)], {"sparse": True}), ([("method", A), ("status", A)], {})],
        "affiliate_links": [([("merchant_id", A), ("token", A)], {"unique": True}), ([("affiliate_id", A)], {})],
        "affiliate_codes": [
            ([("merchant_id", A), ("code", A)], {"unique": True}),
            ([("merchant_id", A), ("stripe_promotion_code_id", A)], {"sparse": True}),
            ([("affiliate_id", A)], {}),
        ],
        "events": [([("merchant_id", A), ("created_at", D)], {})],
        "audit_log": [([("merchant_id", A), ("created_at", D)], {}), ([("merchant_id", A), ("target", A), ("created_at", D)], {})],
        # Every Stripe event Kickrail received, for 90 days: history, and a skip for ones already handled.
        "stripe_events": [
            ([("received_at", A)], {"expireAfterSeconds": 90 * 86400}),
            ([("merchant_id", A), ("received_at", D)], {}),
            ([("status", A), ("received_at", D)], {}),
        ],
        "webhook_endpoints": [([("merchant_id", A)], {})],
        "webhook_deliveries": [([("status", A), ("next_attempt_at", A)], {}), ([("endpoint_id", A), ("created_at", D)], {}), ([("event_id", A)], {})],
        "emails": [([("status", A), ("next_attempt_at", A)], {}), ([("merchant_id", A), ("created_at", D)], {})],
        "invites": [([("token_hash", A)], {"unique": True}), ([("merchant_id", A)], {})],
    }
    await _migrate_portal_domains(db)
    await _migrate_referral_indexes(db)
    for name, indexes in specs.items():
        for keys, opts in indexes:
            await db[name].create_index(keys, **opts)


async def _migrate_referral_indexes(db: AsyncDatabase) -> None:
    """The person lookups on referrals started as plain sparse indexes; they are unique now."""
    info = await db.referrals.index_information()
    for field in ("stripe_customer_id", "email", "external_user_id"):
        name = f"merchant_id_1_{field}_1"
        if name in info and not info[name].get("unique"):
            await db.referrals.drop_index(name)


async def _migrate_portal_domains(db: AsyncDatabase) -> None:
    """One portal domain per program became a list (portal_domains, one marked primary)."""
    async for m in db.merchants.find({"portal_domain": {"$exists": True}}, {"portal_domain": 1}):
        d = m["portal_domain"]
        await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"portal_domains": [d | {"primary": True}] if d else []}, "$unset": {"portal_domain": ""}})
    if "portal_domain.host_1" in await db.merchants.index_information():
        await db.merchants.drop_index("portal_domain.host_1")
