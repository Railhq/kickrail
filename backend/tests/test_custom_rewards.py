"""Campaigns whose reward isn't cash: Kickrail records who earned what and when, the merchant hands it out."""

import time

from tests.conftest import send_event


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


def invoice(inv_id, customer, cents):
    paid = int(time.time())
    return {"id": inv_id, "customer": customer, "amount_paid": cents, "currency": "usd", "status_transitions": {"paid_at": paid}, "created": paid, "lines": {"data": []}}


CUSTOM = {
    "name": "Customer referral", "rule_type": "percent", "percent": 100, "duration_mode": "once", "hold_days": 0, "min_payout_cents": 0,
    "lead_bounty_cents": 500,  # ignored: custom campaigns make no commissions
    "reward_type": "custom", "affiliate_reward": "50% off forever", "affiliate_reward_on": "first_payment", "affiliate_reward_limit": "once",
    "customer_reward": "25% off", "customer_reward_on": "signup",
}


async def test_custom_rewards(client, db):
    owner = await signup(client, db, "owner@rwd.example", "Rhea")
    r = (await client.post("/merchant", json={"name": "Rewardco", "website": "https://rewardco.example"}, headers=auth(owner))).json()
    mid, sk = r["merchant"]["id"], {"authorization": f"Bearer {r['secret_key']}"}
    assert (await client.post("/merchant/stripe", json={"restricted_key": "rk_test_rewardco"}, headers=auth(owner))).status_code == 200
    camp = (await client.get("/merchant/campaigns", headers=auth(owner))).json()[0]["id"]

    assert (await client.put(f"/merchant/campaigns/{camp}", json={**CUSTOM, "affiliate_reward": " "}, headers=auth(owner))).status_code == 422
    r = await client.put(f"/merchant/campaigns/{camp}", json=CUSTOM, headers=auth(owner))
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["reward"]["affiliate"] == {"description": "50% off forever", "on": "first_payment", "limit": "once"} and c["lead_bounty"] is None
    assert c["description"] == "50% off forever when a referral first pays, once; the referred customer gets 25% off at signup"
    assert (await client.post("/merchant/webhooks", json={"url": "https://hooks.globex.com/rwd", "events": ["reward.earned", "reward.fulfilled"]}, headers=auth(owner))).status_code == 200

    # The merchant's app makes each customer an affiliate, with no email.
    r = await client.post("/v1/affiliates", json={"email": "sharer@rwd.example", "name": "Sam", "token": "sam", "metadata": {"user_id": "u_1"}, "send_welcome_email": False}, headers=sk)
    assert r.status_code == 200, r.text
    aff = r.json()["id"]
    assert not await db.emails.find_one({"merchant_id": mid, "to": "sharer@rwd.example"})

    async def events(type_):
        return [e["data"] for e in await db.events.find({"merchant_id": mid, "type": type_}).sort("created_at", 1).to_list(None)]

    # Signup: the referred customer's reward, nothing for the sharer yet.
    r = await client.post("/v1/referrals", json={"via": "sam", "email": "friend1@else.example", "user_id": "u_2", "stripe_customer_id": "cus_r1"}, headers=sk)
    ref1 = r.json()["referral"]["id"]
    [earned] = await events("reward.earned")
    assert earned["recipient"] == "customer" and earned["description"] == "25% off" and earned["referral_id"] == ref1
    assert earned["customer"] == {"email": "friend1@else.example", "user_id": "u_2", "stripe_customer_id": "cus_r1"}

    # First payment: the sharer's reward, and no commission at all.
    hook = f"/webhooks/stripe/{mid}"
    r = await send_event(client, hook, "whsec_merchant", "invoice.paid", invoice("in_r1", "cus_r1", 4425))
    assert r.json()["outcome"] == "rewards earned: 1", r.text
    assert await db.commissions.count_documents({"merchant_id": mid}) == 0
    assert (await db.referrals.find_one({"_id": ref1}))["status"] == "customer"
    sharer = (await events("reward.earned"))[-1]
    assert sharer["recipient"] == "affiliate" and sharer["affiliate_id"] == aff and sharer["description"] == "50% off forever"
    # Stripe sending it again, or a renewal, earns nothing more.
    await send_event(client, hook, "whsec_merchant", "invoice.paid", invoice("in_r1", "cus_r1", 4425))
    assert (await send_event(client, hook, "whsec_merchant", "invoice.paid", invoice("in_r1b", "cus_r1", 4425))).json()["outcome"] == "no reward"

    # "once": a second friend paying gets the friend their discount, but not the sharer another one.
    await client.post("/v1/referrals", json={"via": "sam", "email": "friend2@else.example", "stripe_customer_id": "cus_r2"}, headers=sk)
    await send_event(client, hook, "whsec_merchant", "invoice.paid", invoice("in_r2", "cus_r2", 4425))
    assert [(e["recipient"]) for e in await events("reward.earned")] == ["customer", "affiliate", "customer"]

    # The app fulfils over the API; repeating it is harmless and sends one event.
    r = await client.post(f"/v1/rewards/{sharer['id']}/fulfill", json={"note": "coupon 50_off_forever"}, headers=sk)
    assert r.status_code == 200 and r.json()["status"] == "fulfilled" and r.json()["note"] == "coupon 50_off_forever"
    assert (await client.post(f"/v1/rewards/{sharer['id']}/fulfill", headers=sk)).json()["status"] == "fulfilled"
    assert len(await events("reward.fulfilled")) == 1
    listed = (await client.get("/v1/rewards", params={"status": "earned"}, headers=sk)).json()["data"]
    assert sorted(w["recipient"] for w in listed) == ["customer", "customer"]

    # The dashboard list, and undoing a mistaken fulfil.
    page = (await client.get("/merchant/rewards", headers=auth(owner))).json()
    assert page["total"] == 3 and page["counts"] == {"earned": 2, "fulfilled": 1}
    assert {w["customer_email"] for w in page["items"]} == {"friend1@else.example", "friend2@else.example"}
    assert (await client.post(f"/merchant/rewards/{sharer['id']}/unfulfill", headers=auth(owner))).json()["status"] == "earned"
    assert (await client.post(f"/merchant/rewards/{sharer['id']}/fulfill", json={"note": "by hand"}, headers=auth(owner))).json()["status"] == "fulfilled"

    # The sharer sees rewards, not money.
    view = (await client.get(f"/merchant/affiliates/{aff}/view", headers=auth(owner))).json()
    assert view["reward_mode"] == "custom" and [w["description"] for w in view["rewards"]] == ["50% off forever"]
    assert view["totals"] == {} and view["program"]["terms"].startswith("50% off forever")

    # Never paid cash, so never asked for a tax form.
    assert aff not in [r["affiliate_id"] for r in (await client.get("/merchant/tax", headers=auth(owner))).json()["affiliates"]]

    # A referral that already had a reward handed out can't be deleted.
    assert (await client.delete(f"/merchant/referrals/{ref1}", headers=auth(owner))).status_code == 409


async def test_held_reward_waits_for_review(client, db):
    owner = await signup(client, db, "owner@held.example", "Hal")
    r = (await client.post("/merchant", json={"name": "Heldco", "website": "https://heldco.example"}, headers=auth(owner))).json()
    mid, sk = r["merchant"]["id"], {"authorization": f"Bearer {r['secret_key']}"}
    camp = (await client.get("/merchant/campaigns", headers=auth(owner))).json()[0]["id"]
    await client.put(f"/merchant/campaigns/{camp}", json={**CUSTOM, "affiliate_reward_on": "signup", "affiliate_reward_limit": "per_referral", "customer_reward": ""}, headers=auth(owner))
    aff = (await client.post("/v1/affiliates", json={"email": "self@held.example", "name": "Selma", "token": "selma", "send_welcome_email": False}, headers=sk)).json()["id"]

    # Referring yourself: the reward is recorded but held, and no webhook goes out.
    ref = (await client.post("/v1/referrals", json={"via": "selma", "email": "self+alt@held.example"}, headers=sk)).json()["referral"]
    assert ref["flagged"]
    [w] = await db.rewards.find({"merchant_id": mid}).to_list(None)
    assert w["held"] and w["affiliate_id"] == aff
    assert not await db.events.find_one({"merchant_id": mid, "type": "reward.earned"})
    assert (await client.post(f"/v1/rewards/{w['_id']}/fulfill", headers=sk)).status_code == 409

    # Approving releases it.
    assert (await client.post(f"/merchant/referrals/{ref['id']}/clear", headers=auth(owner))).status_code == 200
    assert await db.events.find_one({"merchant_id": mid, "type": "reward.earned", "data.id": w["_id"]})

    # Rejecting voids the ones not handed out.
    ref2 = (await client.post("/v1/referrals", json={"via": "selma", "email": "self+two@held.example"}, headers=sk)).json()["referral"]
    assert (await client.post(f"/merchant/referrals/{ref2['id']}/reject", headers=auth(owner))).status_code == 200
    w2 = await db.rewards.find_one({"referral_id": ref2["id"]})
    assert w2["status"] == "void" and w2["void_reason"] == "referral rejected"

    # Deleting a referral whose rewards weren't handed out takes them with it.
    assert (await client.delete(f"/merchant/referrals/{ref['id']}", headers=auth(owner))).status_code == 200
    assert not await db.rewards.find_one({"referral_id": ref["id"]})
