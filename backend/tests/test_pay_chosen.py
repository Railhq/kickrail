"""Marking chosen commissions paid from an affiliate's page, including ones not yet due."""

from datetime import UTC, datetime, timedelta

from app.ids import new_id


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


async def test_pay_chosen_commissions_early(client, db):
    owner = await signup(client, db, "owner@early.example", "Eve")
    h = auth(owner)
    mid = (await client.post("/merchant", json={"name": "Earlyco", "website": "https://earlyco.example"}, headers=h)).json()["merchant"]["id"]
    aff = (await client.post("/programs/earlyco/join", json={}, headers=auth(await signup(client, db, "aff@early.example", "Ari")))).json()
    camp = (await db.affiliates.find_one({"_id": aff["id"]}))["campaign_id"]
    await db.affiliates.update_one({"_id": aff["id"]}, {"$set": {"status": "approved"}})
    await db.campaigns.update_one({"_id": camp}, {"$set": {"min_payout_cents": 100_000}})
    now = datetime.now(UTC)

    async def commission(cents, due_in_days, currency="usd", **kw):
        cid = new_id("com")
        await db.commissions.insert_one({
            "_id": cid, "merchant_id": mid, "affiliate_id": aff["id"], "campaign_id": camp, "referral_id": "ref_x", "kind": "sale",
            "amount_cents": cents, "currency": currency, "base_cents": cents * 2, "status": "pending", "source_key": new_id("src"),
            "due_at": now + timedelta(days=due_in_days), "created_at": now, **kw,
        })
        return cid

    due = await commission(1000, -2)
    early = await commission(3160, 20)
    later = await commission(500, 25)
    inr = await commission(199960, 21, "inr")
    held = await commission(700, -1, held=True)

    # The affiliate page lists due and not-yet-due commissions separately; held ones count as not yet.
    async def ids(**params):
        return {c["id"] for c in (await client.get("/merchant/commissions", params={"affiliate_id": aff["id"], **params}, headers=h)).json()["items"]}
    assert await ids(due="true") == {due}
    assert await ids(due="false") == {early, later, inr, held}
    # Under the minimum payout, so Ready to pay has nothing.
    assert (await client.get("/merchant/payouts", headers=h)).json()["payable"] == []

    r = await client.post("/merchant/payouts/commissions", json={"commission_ids": [held]}, headers=h)
    assert r.status_code == 400 and "held for review" in r.json()["detail"]

    r = await client.post("/merchant/payouts/commissions", json={"commission_ids": [due, early, inr, early], "reference": "Paid in Rewardful"}, headers=h)
    assert r.status_code == 200, r.text
    inr_po, usd_po = sorted(r.json(), key=lambda p: p["currency"])
    assert usd_po["total_cents"] == 4160 and usd_po["status"] == "paid" and usd_po["reference"] == "Paid in Rewardful" and usd_po["early_commission_ids"] == [early]
    assert inr_po["total_cents"] == 199960 and inr_po["items"][0]["commission_ids"] == [inr]
    paid = {c["_id"]: c async for c in db.commissions.find({"merchant_id": mid})}
    assert all(paid[c]["status"] == "paid" and paid[c]["payout_id"] for c in (due, early, inr))
    assert paid[later]["status"] == "pending" and "payout_id" not in paid[later] and paid[held]["status"] == "pending"
    log = await db.audit_log.find_one({"merchant_id": mid, "target": usd_po["id"]})
    assert log["detail"]["paid_early"] == 1

    # Can't be paid twice, and Undo puts them back.
    assert (await client.post("/merchant/payouts/commissions", json={"commission_ids": [early]}, headers=h)).status_code == 400
    assert (await client.post(f"/merchant/payouts/{usd_po['id']}/undo", headers=h)).status_code == 200
    assert (await db.commissions.find_one({"_id": early}))["status"] == "pending"

    # A clawback can be paid with its affiliate's commissions, but not on its own.
    claw = await commission(-200, -1)
    assert (await client.post("/merchant/payouts/commissions", json={"commission_ids": [claw]}, headers=h)).status_code == 400
    r = await client.post("/merchant/payouts/commissions", json={"commission_ids": [claw, early]}, headers=h)
    assert r.status_code == 200 and r.json()[0]["total_cents"] == 2960
