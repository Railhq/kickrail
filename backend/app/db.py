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
        "referrals": [
            ([("merchant_id", A), ("stripe_customer_id", A)], {"sparse": True}),
            ([("merchant_id", A), ("email", A)], {"sparse": True}),
            ([("merchant_id", A), ("external_user_id", A)], {"sparse": True}),
            ([("merchant_id", A), ("affiliate_id", A), ("created_at", D)], {}),
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
        "webhook_endpoints": [([("merchant_id", A)], {})],
        "webhook_deliveries": [([("status", A), ("next_attempt_at", A)], {}), ([("endpoint_id", A), ("created_at", D)], {}), ([("event_id", A)], {})],
        "emails": [([("status", A), ("next_attempt_at", A)], {}), ([("merchant_id", A), ("created_at", D)], {})],
        "invites": [([("token_hash", A)], {"unique": True}), ([("merchant_id", A)], {})],
    }
    await _migrate_portal_domains(db)
    for name, indexes in specs.items():
        for keys, opts in indexes:
            await db[name].create_index(keys, **opts)


async def _migrate_portal_domains(db: AsyncDatabase) -> None:
    """One portal domain per program became a list (portal_domains, one marked primary)."""
    async for m in db.merchants.find({"portal_domain": {"$exists": True}}, {"portal_domain": 1}):
        d = m["portal_domain"]
        await db.merchants.update_one({"_id": m["_id"]}, {"$set": {"portal_domains": [d | {"primary": True}] if d else []}, "$unset": {"portal_domain": ""}})
    if "portal_domain.host_1" in await db.merchants.index_information():
        await db.merchants.drop_index("portal_domain.host_1")
