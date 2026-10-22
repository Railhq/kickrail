"""Deleting and archiving campaigns: only an unused campaign can go; one with history is archived."""


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


CAMPAIGN = {"name": "Creators", "rule_type": "percent", "percent": 40, "duration_mode": "forever", "hold_days": 30, "min_payout_cents": 5000, "public": True, "slug": "creators"}


async def test_delete_and_archive(client, db):
    owner = await signup(client, db, "owner@cdel.example", "Cora")
    r = (await client.post("/merchant", json={"name": "Cdelco", "website": "https://cdel.example"}, headers=auth(owner))).json()
    mid, slug, sk = r["merchant"]["id"], r["merchant"]["slug"], {"authorization": f"Bearer {r['secret_key']}"}
    h = auth(owner)
    default = (await client.get("/merchant/campaigns", headers=h)).json()[0]

    # The default campaign can't go.
    assert "default campaign" in default["delete_blocked"]
    assert (await client.delete(f"/merchant/campaigns/{default['id']}", headers=h)).status_code == 409
    assert (await client.post(f"/merchant/campaigns/{default['id']}/archive", headers=h)).status_code == 409

    # An unused one can, and leaves a tombstone and an audit entry.
    spare = (await client.post("/merchant/campaigns", json={**CAMPAIGN, "name": "Spare", "slug": "spare"}, headers=h)).json()
    listed = {c["id"]: c for c in (await client.get("/merchant/campaigns", headers=h)).json()}
    assert listed[spare["id"]]["delete_blocked"] is None and listed[spare["id"]]["usage"] == {"affiliates": 0, "referrals": 0, "commissions": 0, "rewards": 0}
    assert (await client.delete(f"/merchant/campaigns/{spare['id']}", headers=h)).status_code == 200
    assert not await db.campaigns.find_one({"_id": spare["id"]})
    assert await db.deleted_records.find_one({"kind": "campaign", "record_id": spare["id"]})
    assert await db.audit_log.find_one({"merchant_id": mid, "action": "campaign.deleted"})

    # One with an affiliate says to move them; once it has a referral it says to archive.
    camp = (await client.post("/merchant/campaigns", json=CAMPAIGN, headers=h)).json()
    aff = (await client.post("/v1/affiliates", json={"email": "c1@cdel.example", "name": "C", "token": "cone", "campaign_id": camp["id"], "send_welcome_email": False}, headers=sk)).json()
    r = await client.delete(f"/merchant/campaigns/{camp['id']}", headers=h)
    assert r.status_code == 409 and "Move them" in r.json()["detail"]
    await client.post("/v1/referrals", json={"via": "cone", "email": "friend@else.example"}, headers=sk)
    r = await client.delete(f"/merchant/campaigns/{camp['id']}", headers=h)
    assert r.status_code == 409 and "1 referral" in r.json()["detail"] and "Archive" in r.json()["detail"]

    # Archived: its join page is gone, nobody new can join or be moved in, it can't be the default.
    assert (await client.get(f"/programs/{slug}/campaigns/creators")).status_code == 200
    assert (await client.post(f"/merchant/campaigns/{camp['id']}/archive", headers=h)).status_code == 200
    assert (await client.get(f"/programs/{slug}/campaigns/creators")).status_code == 404
    r = await client.post("/v1/affiliates", json={"email": "c2@cdel.example", "name": "D", "campaign_id": camp["id"], "send_welcome_email": False}, headers=sk)
    assert r.status_code == 409
    other = (await client.post("/v1/affiliates", json={"email": "c3@cdel.example", "name": "E", "send_welcome_email": False}, headers=sk)).json()
    assert (await client.patch(f"/merchant/affiliates/{other['id']}", json={"campaign_id": camp["id"]}, headers=h)).status_code == 409
    assert (await client.post(f"/merchant/campaigns/{camp['id']}/default", headers=h)).status_code == 409
    listed = {c["id"]: c for c in (await client.get("/merchant/campaigns", headers=h)).json()}
    assert listed[camp["id"]]["archived"] is True and listed[camp["id"]]["usage"]["referrals"] == 1

    # The affiliate already in it keeps earning: referrals still attach to them.
    r = await client.post("/v1/referrals", json={"via": "cone", "email": "friend2@else.example"}, headers=sk)
    assert r.json()["referral"]["affiliate_id"] == aff["id"]

    # Unarchiving reopens it.
    assert (await client.post(f"/merchant/campaigns/{camp['id']}/unarchive", headers=h)).status_code == 200
    assert (await client.get(f"/programs/{slug}/campaigns/creators")).status_code == 200
