"""Removing an operator (users) who has nothing in Kickrail.

When someone deletes their Railhq account, Kickrail keeps their programs (the account page
promises each tool keeps its data). An operator with no data of their own, such as a
sign-up that never made a program, is removed outright instead of left behind unlinked.

Sign-up creates only the users record; a program, team seat or payout account comes later,
so any of those counts as data. Sessions are signed tokens checked against users, so they
stop working once the record is gone."""

from pymongo.asynchronous.database import AsyncDatabase

# Fields on users that only exist once someone did something real.
_REAL_FIELDS = ("connect_account_id", "stripe_customer_id", "paypal_email", "payout_method")


async def has_data(db: AsyncDatabase, user: dict) -> bool:
    uid = user["_id"]
    if any(user.get(f) for f in _REAL_FIELDS):
        return True
    if await db.merchants.find_one({"$or": [{"owner_id": uid}, {"member_ids": uid}]}, {"_id": 1}):
        return True
    if await db.invites.find_one({"user_id": uid}, {"_id": 1}):
        return True
    # affiliates.user_id is a partner id, but an operator id there would be data too.
    return bool(await db.affiliates.find_one({"user_id": uid}, {"_id": 1}))


async def remove_if_empty(db: AsyncDatabase, user: dict) -> bool:
    """Delete the operator if they have no data; True when deleted."""
    if await has_data(db, user):
        return False
    res = await db.users.delete_one({"_id": user["_id"]})
    return res.deleted_count == 1
