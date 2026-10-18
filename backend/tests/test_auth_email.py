"""Email verification and password reset."""

import re
from datetime import UTC, datetime, timedelta


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def link(db, to, kind):
    mail = await db.emails.find_one({"to": to, "kind": kind}, sort=[("created_at", -1)])
    assert mail and mail["from"] == "Kickrail <noreply@kickrail.test>", mail
    return re.search(r"token=([\w%-]+)", mail["text"]).group(1)


async def test_signup_must_verify_before_using_the_app(client, db):
    r = await client.post("/auth/signup", json={"email": "vera@verify.example", "password": "correct-horse", "name": "Vera", "next": "/join/acme"})
    tok = r.json()["token"]
    me = (await client.get("/auth/me", headers=auth(tok))).json()
    assert me["user"]["email_verified"] is False
    # Signed in, but nothing else works yet.
    r = await client.post("/merchant", json={"name": "Vera Co", "website": "https://vera.example"}, headers=auth(tok))
    assert r.status_code == 403 and "verify your email" in r.json()["detail"]
    assert (await client.get("/portal", headers=auth(tok))).status_code == 403

    first = await link(db, "vera@verify.example", "verify_email")
    assert (await client.post("/auth/verify/resend", json={}, headers=auth(tok))).status_code == 429
    await db.users.update_one({"email": "vera@verify.example"}, {"$set": {"verify_sent_at": datetime.now(UTC) - timedelta(minutes=2)}})
    assert (await client.post("/auth/verify/resend", json={}, headers=auth(tok))).status_code == 200
    token = await link(db, "vera@verify.example", "verify_email")
    assert token != first
    assert (await client.post("/auth/verify", json={"token": first})).status_code == 400  # replaced by the resend

    r = await client.post("/auth/verify", json={"token": token})
    assert r.status_code == 200 and r.json() == {"ok": True, "email": "vera@verify.example", "next": "/join/acme"}
    assert (await client.post("/auth/verify", json={"token": token})).status_code == 400
    assert (await client.get("/auth/me", headers=auth(tok))).json()["user"]["email_verified"] is True
    r = await client.post("/merchant", json={"name": "Vera Co", "website": "https://vera.example"}, headers=auth(tok))
    assert r.status_code == 200, r.text


async def test_expired_verify_link(client, db):
    await client.post("/auth/signup", json={"email": "late@verify.example", "password": "correct-horse", "name": "Late"})
    token = await link(db, "late@verify.example", "verify_email")
    await db.users.update_one({"email": "late@verify.example"}, {"$set": {"verify_expires_at": datetime.now(UTC) - timedelta(seconds=1)}})
    assert (await client.post("/auth/verify", json={"token": token})).status_code == 400


async def test_accounts_from_before_verification_still_work(client, db):
    r = await client.post("/auth/signup", json={"email": "old@verify.example", "password": "correct-horse", "name": "Old"})
    await db.users.update_one({"email": "old@verify.example"}, {"$unset": {"email_verified": ""}})
    assert (await client.get("/portal", headers=auth(r.json()["token"]))).status_code == 200


async def test_password_reset(client, db):
    r = await client.post("/auth/signup", json={"email": "rita@reset.example", "password": "first-password", "name": "Rita"})
    old_session = r.json()["token"]
    # Unknown addresses get the same answer and no mail.
    assert (await client.post("/auth/password/forgot", json={"email": "nobody@reset.example"})).json() == {"ok": True}
    assert not await db.emails.find_one({"to": "nobody@reset.example"})

    assert (await client.post("/auth/password/forgot", json={"email": "RITA@reset.example"})).json() == {"ok": True}
    token = await link(db, "rita@reset.example", "password_reset")
    # A second ask within a minute sends nothing new.
    await client.post("/auth/password/forgot", json={"email": "rita@reset.example"})
    assert await db.emails.count_documents({"to": "rita@reset.example", "kind": "password_reset"}) == 1

    assert (await client.post("/auth/password/reset", json={"token": token, "password": "short"})).status_code == 422
    r = await client.post("/auth/password/reset", json={"token": token, "password": "second-password"})
    assert r.status_code == 200, r.text
    new_session = r.json()["token"]
    assert (await client.post("/auth/password/reset", json={"token": token, "password": "third-password"})).status_code == 400

    # Old sessions are signed out; the reset also proved the address.
    assert (await client.get("/auth/me", headers=auth(old_session))).status_code == 401
    assert (await client.get("/auth/me", headers=auth(new_session))).json()["user"]["email_verified"] is True
    assert (await client.post("/auth/login", json={"email": "rita@reset.example", "password": "first-password"})).status_code == 401
    assert (await client.post("/auth/login", json={"email": "rita@reset.example", "password": "second-password"})).status_code == 200


async def test_reset_takes_back_an_address_someone_else_signed_up_with(client, db):
    # Mallory signs up with Sam's address; she can never verify it.
    await client.post("/auth/signup", json={"email": "sam@owner.example", "password": "mallory-pass", "name": "Sam"})
    mallory = (await client.post("/auth/login", json={"email": "sam@owner.example", "password": "mallory-pass"})).json()["token"]
    # Sam resets the password from the email only Sam receives.
    await client.post("/auth/password/forgot", json={"email": "sam@owner.example"})
    token = await link(db, "sam@owner.example", "password_reset")
    sam = (await client.post("/auth/password/reset", json={"token": token, "password": "sams-own-pass"})).json()["token"]
    assert (await client.get("/auth/me", headers=auth(mallory))).status_code == 401
    assert (await client.get("/portal", headers=auth(sam))).status_code == 200


async def test_links_open_on_the_portal_domain_they_came_from(client, db):
    await db.merchants.insert_one({"_id": "mer_portal", "name": "Portal Co", "slug": "portal-co", "public_key": "pk_portal", "secret_key_hash": "h1", "portal_domains": [{"host": "partners.portal.example", "verified": True}]})
    await db.merchants.insert_one({"_id": "mer_unverified", "name": "Half", "slug": "half", "public_key": "pk_half", "secret_key_hash": "h2", "portal_domains": [{"host": "aff.half.example", "verified": False}]})
    sites = {"https://partners.portal.example": "https://partners.portal.example/", "https://aff.half.example": "https://kickrail.test/", "https://evil.example": "https://kickrail.test/", None: "https://kickrail.test/"}
    for i, (site, base) in enumerate(sites.items()):
        email = f"p{i}@portal.example"
        await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": "P", "site": site})
        mail = await db.emails.find_one({"to": email, "kind": "verify_email"})
        assert f"{base}verify?token=" in mail["text"], (site, mail["text"])
    await client.post("/auth/password/forgot", json={"email": "p0@portal.example", "site": "https://partners.portal.example"})
    mail = await db.emails.find_one({"to": "p0@portal.example", "kind": "password_reset"})
    assert "https://partners.portal.example/reset?token=" in mail["text"]
