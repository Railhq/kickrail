"""payout.due and recording a payout over the API, for programs that reward in kind."""

from datetime import UTC, datetime, timedelta

from app.ids import new_id
from app.services.payouts import announce_due


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


async def test_payout_due_then_record_payout(client, db):
    owner = await signup(client, db, "owner@due.example", "Dee")
    r = (await client.post("/merchant", json={"name": "Dueco", "website": "https://dueco.example"}, headers=auth(owner))).json()
    mid, sk = r["merchant"]["id"], {"authorization": f"Bearer {r['secret_key']}"}
    assert (await client.post("/merchant/webhooks", json={"url": "https://hooks.globex.com/due", "events": ["payout.due"]}, headers=auth(owner))).status_code == 200
    aff_token = await signup(client, db, "friend@due.example", "Fay")
    aff = (await client.post("/programs/dueco/join", json={}, headers=auth(aff_token))).json()
    camp = (await db.affiliates.find_one({"_id": aff["id"]}))["campaign_id"]
    await db.affiliates.update_one({"_id": aff["id"]}, {"$set": {"status": "approved", "metadata": {"user_id": "u_42"}}})
    now = datetime.now(UTC)

    async def commission(cents, due_in_days):
        await db.commissions.insert_one({
            "_id": new_id("com"), "merchant_id": mid, "affiliate_id": aff["id"], "campaign_id": camp, "referral_id": "ref_x", "kind": "sale",
            "amount_cents": cents, "currency": "usd", "sale_amount_cents": cents * 4, "status": "pending", "source_key": new_id("src"),
            "due_at": now + timedelta(days=due_in_days), "created_at": now,
        })

    async def due_events():
        return await db.events.find({"merchant_id": mid, "type": "payout.due"}).to_list(None)

    await db.campaigns.update_one({"_id": camp}, {"$set": {"min_payout_cents": 1000}})
    await commission(1500, 5)
    await commission(800, -1)
    assert await announce_due(db) == 0  # one still in its hold, the other under the minimum payout
    await db.commissions.delete_many({"merchant_id": mid, "amount_cents": 800})

    await commission(2500, -1)
    await announce_due(db)
    [ev] = await due_events()
    d = ev["data"]
    assert d["affiliate_id"] == aff["id"] and d["campaign_id"] == camp and d["email"] == "friend@due.example"
    assert d["amount_cents"] == 2500 and d["currency"] == "usd" and d["metadata"] == {"user_id": "u_42"} and len(d["commission_ids"]) == 1
    assert await db.webhook_deliveries.count_documents({"event_id": ev["_id"]}) == 1

    # Announced once, and a clawback on the same balance isn't news.
    await announce_due(db)
    await commission(-500, -1)
    await announce_due(db)
    assert len(await due_events()) == 1

    # Recording the payout pays exactly what was payable; the held one stays.
    assert (await client.post("/v1/payouts", json={"affiliate_ids": ["aff_nobody"]}, headers=sk)).status_code == 409
    r = await client.post("/v1/payouts", json={"affiliate_ids": [aff["id"]], "reference": "coupon 50_off_forever"}, headers=sk)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["method"] == "manual" and p["status"] == "paid" and p["total_cents"] == 2000 and p["reference"] == "coupon 50_off_forever"
    assert await db.commissions.count_documents({"merchant_id": mid, "status": "paid"}) == 2
    assert await db.events.count_documents({"merchant_id": mid, "type": "payout.paid"}) == 1
    assert (await client.post("/v1/payouts", json={"affiliate_ids": [aff["id"]]}, headers=sk)).status_code == 409

    # The next commission to come due is announced on its own.
    await db.commissions.update_many({"merchant_id": mid, "status": "pending"}, {"$set": {"due_at": now - timedelta(minutes=1)}})
    await announce_due(db)
    assert sorted(e["data"]["amount_cents"] for e in await due_events()) == [1500, 2500]
