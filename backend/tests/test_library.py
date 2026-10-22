"""Ownership transfer, hosted terms, the asset library and the self-referral settings."""

from tests.test_custom_rewards import auth, signup


async def program(client, db, slug):
    owner = await signup(client, db, f"owner@{slug}.example", "Olive")
    r = (await client.post("/merchant", json={"name": slug.title(), "website": f"https://{slug}.example"}, headers=auth(owner))).json()
    return owner, r["merchant"]["id"], {"authorization": f"Bearer {r['secret_key']}"}


async def test_transfer_ownership(client, db):
    owner, mid, _ = await program(client, db, "handover")
    mate = await signup(client, db, "mate@handover.example", "Mo")
    mate_id = (await db.users.find_one({"email": "mate@handover.example"}))["_id"]
    stranger = (await db.users.find_one({"email": "owner@handover.example"}))["_id"]
    await db.merchants.update_one({"_id": mid}, {"$push": {"member_ids": mate_id}})

    # Only the owner hands over, and only to a member.
    assert (await client.post("/merchant/team/owner", json={"user_id": stranger}, headers=auth(mate))).status_code == 403
    assert (await client.post("/merchant/team/owner", json={"user_id": "usr_nobody"}, headers=auth(owner))).status_code == 404
    assert (await client.post("/merchant/team/owner", json={"user_id": mate_id}, headers=auth(owner))).status_code == 200
    t = (await client.get("/merchant/team", headers=auth(mate))).json()
    assert t["owner_id"] == mate_id and len(t["members"]) == 2
    assert await db.audit_log.find_one({"merchant_id": mid, "action": "team.owner_changed", "target": mate_id})
    # The old owner is a plain member now.
    assert (await client.delete(f"/merchant/team/members/{mate_id}", headers=auth(owner))).status_code == 400


async def test_hosted_terms(client, db):
    owner, mid, _ = await program(client, db, "termsco")
    assert (await client.get("/programs/termsco/terms")).status_code == 404
    html = '<p>Be <b>nice</b>.<script>alert(1)</script></p><ul><li onclick="x()">No spam</li></ul><a href="javascript:alert(1)">x</a><a href="https://termsco.example/faq">FAQ</a>'
    r = await client.put("/merchant/terms", json={"title": "Partner terms", "html": html}, headers=auth(owner))
    assert r.status_code == 200, r.text
    stored = r.json()["terms"]["html"]
    assert "script" not in stored and "onclick" not in stored and "javascript" not in stored
    assert "<b>nice</b>" in stored and 'href="https://termsco.example/faq"' in stored and "nofollow" in stored

    page = (await client.get("/programs/termsco/terms")).json()
    assert page["terms"]["title"] == "Partner terms" and page["program"]["name"] == "Termsco"
    assert (await client.get("/programs/termsco")).json()["has_terms"] is True

    # An external page is kept alongside, and saving branding without it leaves it alone.
    r = await client.put("/merchant/terms", json={"title": "Partner terms", "html": html, "external_url": "https://termsco.example/terms"}, headers=auth(owner))
    assert r.json()["branding"]["terms_url"] == "https://termsco.example/terms"
    r = await client.put("/merchant/branding", json={"color": "#112233", "logo_url": None}, headers=auth(owner))
    assert r.json()["branding"] == {"color": "#112233", "terms_url": "https://termsco.example/terms"}

    # Clearing the editor removes the page.
    assert (await client.put("/merchant/terms", json={"title": "x", "html": "<p></p>"}, headers=auth(owner))).json()["terms"] is None
    assert (await client.get("/programs/termsco/terms")).status_code == 404

    # "terms" can't be a campaign's join page name, since it is the terms page's path.
    r = await client.post("/merchant/campaigns", json={"name": "Terms", "slug": "terms", "public": True, "rule_type": "percent", "percent": 10, "duration_mode": "once", "hold_days": 0, "min_payout_cents": 0}, headers=auth(owner))
    assert r.status_code == 422, r.text


async def test_asset_library(client, db):
    owner, mid, sk = await program(client, db, "assetco")
    h = auth(owner)

    # Uploads: the raw file is the body.
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = await client.post("/merchant/files", params={"name": "banner.png"}, content=png, headers={**h, "content-type": "image/png"})
    assert r.status_code == 200, r.text
    img = r.json()
    assert img["url"].endswith(f"/api/files/{img['id']}/banner.png") and img["size"] == len(png)
    pdf = (await client.post("/merchant/files", params={"name": "guide.pdf"}, content=b"%PDF-1.4", headers={**h, "content-type": "application/pdf"})).json()
    # A logo must be an image, and small.
    assert (await client.post("/merchant/files", params={"kind": "logo", "name": "x.pdf"}, content=b"%PDF", headers={**h, "content-type": "application/pdf"})).status_code == 422
    assert (await client.post("/merchant/files", params={"kind": "logo", "name": "big.png"}, content=b"0" * (1024 * 1024 + 1), headers={**h, "content-type": "image/png"})).status_code == 413

    # Images are served inline, anything else as a download, and never able to run script.
    served = await client.get(f"/files/{img['id']}/banner.png")
    assert served.status_code == 200 and served.content == png and served.headers["content-type"] == "image/png"
    assert "sandbox" in served.headers["content-security-policy"]
    dl = await client.get(f"/files/{pdf['id']}/guide.pdf")
    assert dl.headers["content-disposition"].startswith("attachment") and dl.headers["content-type"] == "application/octet-stream"

    async def add(**body):
        r = await client.post("/merchant/assets", json=body, headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    assert (await client.post("/merchant/assets", json={"type": "image", "name": "Bad", "file_id": pdf["id"]}, headers=h)).status_code == 422
    assert (await client.post("/merchant/assets", json={"type": "link", "name": "No url"}, headers=h)).status_code == 422
    banner = await add(type="image", name="Banner", file_id=img["id"], status="published")
    await add(type="file", name="Media kit", file_id=pdf["id"])
    await add(type="link", name="Pricing page", url="https://assetco.example/pricing", status="published")
    await add(type="link", name="Elsewhere", url="https://other.example/post", status="published")
    await add(type="text", name="Tweet", text="Try Assetco with my link {link} or code {code}", status="published")

    page = (await client.get("/merchant/assets", headers=h)).json()
    assert page["counts"] == {"all": 5, "published": 4, "draft": 1} and page["storage"]["used"] == len(png) + 8
    assert [a["name"] for a in (await client.get("/merchant/assets", params={"status": "draft"}, headers=h)).json()["items"]] == ["Media kit"]
    assert [a["name"] for a in (await client.get("/merchant/assets", params={"type": "link", "sort": "name"}, headers=h)).json()["items"]] == ["Elsewhere", "Pricing page"]
    assert [a["name"] for a in (await client.get("/merchant/assets", params={"q": "TWE"}, headers=h)).json()["items"]] == ["Tweet"]

    # Affiliates see published ones, with their own link filled in.
    aff = (await client.post("/v1/affiliates", json={"email": "pat@else.example", "name": "Pat", "token": "pat", "code": "PAT10", "send_welcome_email": False}, headers=sk)).json()["id"]
    view = (await client.get(f"/merchant/affiliates/{aff}/view", headers=h)).json()
    got = {a["name"]: a for a in view["assets"]}
    assert set(got) == {"Banner", "Pricing page", "Elsewhere", "Tweet"}
    assert got["Pricing page"]["url"] == "https://assetco.example/pricing?via=pat"
    assert got["Elsewhere"]["url"] == "https://other.example/post"
    assert got["Tweet"]["text"] == "Try Assetco with my link https://assetco.example/?via=pat or code PAT10"
    assert got["Banner"]["file"]["url"] == img["url"]

    # Unpublishing hides it; deleting removes its file too.
    assert (await client.patch(f"/merchant/assets/{banner['id']}", json={"status": "draft"}, headers=h)).json()["status"] == "draft"
    assert "Banner" not in {a["name"] for a in (await client.get(f"/merchant/affiliates/{aff}/view", headers=h)).json()["assets"]}
    assert (await client.delete(f"/merchant/assets/{banner['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/files/{img['id']}/banner.png")).status_code == 404
    assert await db.audit_log.count_documents({"merchant_id": mid, "action": "asset.deleted"}) == 1


async def test_self_referral_settings(client, db):
    owner, mid, sk = await program(client, db, "selfco")
    aff = (await client.post("/v1/affiliates", json={"email": "sid@selfco-partner.example", "name": "Sid", "token": "sid", "send_welcome_email": False}, headers=sk)).json()["id"]

    # Default: held for review, and the team gets an email.
    ref = (await client.post("/v1/referrals", json={"via": "sid", "email": "sid+2@selfco-partner.example"}, headers=sk)).json()["referral"]
    assert ref["flagged"]
    mail = await db.emails.find_one({"merchant_id": mid, "kind": "self_referral"})
    assert mail and mail["to"] == "owner@selfco.example" and "held until you approve" in mail["text"]

    # Switched to reject outright: no review, nothing earned, still an email.
    r = await client.patch("/merchant", json={"reject_self_referrals": True, "emails": {"self_referral": True}}, headers=auth(owner))
    assert r.json()["settings"]["reject_self_referrals"] is True
    ref2 = (await client.post("/v1/referrals", json={"via": "sid", "email": "sid+3@selfco-partner.example"}, headers=sk)).json()["referral"]
    stored = await db.referrals.find_one({"_id": ref2["id"]})
    assert stored["rejected"] and stored["flags_cleared"] and stored["affiliate_id"] == aff
    assert await db.audit_log.find_one({"merchant_id": mid, "action": "referral.rejected", "target": ref2["id"]})
    assert "rejected automatically" in (await db.emails.find({"merchant_id": mid, "kind": "self_referral"}).sort("created_at", -1).to_list(1))[0]["text"]

    # The email can be switched off.
    await client.patch("/merchant", json={"emails": {"self_referral": False}}, headers=auth(owner))
    await client.post("/v1/referrals", json={"via": "sid", "email": "sid+4@selfco-partner.example"}, headers=sk)
    assert await db.emails.count_documents({"merchant_id": mid, "kind": "self_referral"}) == 2
