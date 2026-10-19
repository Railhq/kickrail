"""Public campaigns get their own join page; each campaign can point links at its own landing page."""

import pytest


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


CAMP = {"rule_type": "percent", "percent": 40, "duration_mode": "forever", "hold_days": 0, "min_payout_cents": 0}


@pytest.fixture(scope="module")
async def prog(client, db):
    token = await signup(client, db, "owner@pages.example", "Pia")
    r = await client.post("/merchant", json={"name": "Pageco", "website": "https://pageco.example"}, headers=auth(token))
    return {"token": token, "id": r.json()["merchant"]["id"]}


async def test_public_campaign_has_a_join_page(client, db, prog):
    h = auth(prog["token"])
    r = await client.post("/merchant/campaigns", json={**CAMP, "name": "Partners", "public": True, "landing_url": "https://pageco.example/partners"}, headers=h)
    c = r.json()
    assert r.status_code == 200 and c["slug"] == "partners" and c["join_url"].endswith("/join/pageco/partners")
    page = (await client.get("/programs/pageco/campaigns/partners")).json()
    assert page["campaign"] == "partners" and page["terms"].startswith("40%")
    # The main join page still describes the default campaign.
    assert (await client.get("/programs/pageco")).json()["campaign"] is None

    aff_token = await signup(client, db, "ann@pages.example", "Ann")
    a = (await client.post("/programs/pageco/join", json={"campaign": "partners"}, headers=auth(aff_token))).json()
    assert a["campaign_id"] == c["id"]
    view = (await client.get(f"/portal/{a['id']}", headers=auth(aff_token))).json()
    assert view["link"].startswith("https://pageco.example/partners?via=")
    listed = next(x for x in (await client.get("/merchant/affiliates", headers=h)).json() if x["id"] == a["id"])
    assert listed["link"] == view["link"]


async def test_private_campaigns_and_bad_input(client, db, prog):
    h = auth(prog["token"])
    r = await client.post("/merchant/campaigns", json={**CAMP, "name": "VIP"}, headers=h)
    assert r.json()["public"] is False and r.json()["join_url"] is None and r.json()["slug"] is None
    await client.put(f"/merchant/campaigns/{r.json()['id']}", json={**CAMP, "name": "VIP", "slug": "vip"}, headers=h)
    assert (await client.get("/programs/pageco/campaigns/vip")).status_code == 404
    bob = await signup(client, db, "bob@pages.example", "Bob")
    assert (await client.post("/programs/pageco/join", json={"campaign": "vip"}, headers=auth(bob))).status_code == 404
    # Plain joins still go to the default campaign.
    a = (await client.post("/programs/pageco/join", json={}, headers=auth(bob))).json()
    default = next(c for c in (await client.get("/merchant/campaigns", headers=h)).json() if c["is_default"])
    assert a["campaign_id"] == default["id"] and default["join_url"].endswith("/join/pageco")
    # Taken names, bad names and off-site landing pages are refused.
    assert (await client.post("/merchant/campaigns", json={**CAMP, "name": "Again", "public": True, "slug": "partners"}, headers=h)).status_code == 409
    assert (await client.post("/merchant/campaigns", json={**CAMP, "name": "Bad", "public": True, "slug": "No Spaces"}, headers=h)).status_code == 422
    assert (await client.post("/merchant/campaigns", json={**CAMP, "name": "Off", "landing_url": "https://elsewhere.example/"}, headers=h)).status_code == 422


async def test_adding_a_coupon_makes_existing_codes_redeemable(client, db, prog, fakes):
    h = auth(prog["token"])
    assert (await client.post("/merchant/stripe", json={"restricted_key": "rk_test_pageco"}, headers=h)).status_code == 200
    c = (await client.post("/merchant/campaigns", json={**CAMP, "name": "Creators"}, headers=h)).json()
    cat = await signup(client, db, "cat@pages.example", "Cat")
    a = (await client.post("/programs/pageco/join", json={}, headers=auth(cat))).json()
    r = await client.patch(f"/merchant/affiliates/{a['id']}", json={"campaign_id": c["id"], "status": "approved", "code": "catcast"}, headers=h)
    assert r.status_code == 200 and not (await db.affiliates.find_one({"_id": a["id"]})).get("stripe_promotion_code_id")
    assert (await client.post(f"/merchant/affiliates/{a['id']}/codes", json={"code": "catpod"}, headers=h)).status_code == 200

    r = await client.put(f"/merchant/campaigns/{c['id']}", json={**CAMP, "name": "Creators", "stripe_coupon_id": "coupon_15"}, headers=h)
    assert r.status_code == 200 and r.json()["warning"] is None
    assert {("coupon_15", "CATCAST"), ("coupon_15", "CATPOD")} <= set(fakes["merchant"].promotion_codes)
    aff = await db.affiliates.find_one({"_id": a["id"]})
    assert aff["stripe_promotion_code_id"] == "promo_CATCAST" and aff["stripe_promotion_code"] == "CATCAST"
    assert (await db.affiliate_codes.find_one({"affiliate_id": a["id"]}))["stripe_promotion_code_id"] == "promo_CATPOD"
    # Saving again with the same coupon doesn't create duplicates.
    n = len(fakes["merchant"].promotion_codes)
    await client.put(f"/merchant/campaigns/{c['id']}", json={**CAMP, "name": "Creators", "stripe_coupon_id": "coupon_15"}, headers=h)
    assert len(fakes["merchant"].promotion_codes) == n
