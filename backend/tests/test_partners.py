"""Affiliates (partners) have their own login, separate from the dashboard's, and the
sessions and links from before the split keep working."""

import re
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings
from app.ids import sha256
from app.security import hash_password


def auth(token):
    return {"authorization": f"Bearer {token}"}


def legacy_token(uid: str, gen: int = 0) -> str:
    """A session issued before the split: no kind claim."""
    now = datetime.now(UTC)
    return jwt.encode({"sub": uid, "gen": gen, "iat": now, "exp": now + timedelta(days=30)}, get_settings().app_secret, algorithm="HS256")


async def latest_link(db, to, kind):
    mail = await db.emails.find_one({"to": to, "kind": kind}, sort=[("created_at", -1)])
    return re.search(r"token=([\w%-]+)", mail["text"]).group(1)


async def program(client, db, slug):
    r = await client.post("/auth/signup", json={"email": f"owner@{slug}.example", "password": "correct-horse", "name": "Owner"})
    await db.users.update_one({"email": f"owner@{slug}.example"}, {"$set": {"email_verified": True}})
    tok = r.json()["token"]
    await client.post("/merchant", json={"name": slug.title(), "website": f"https://{slug}.example"}, headers=auth(tok))
    return tok


async def test_one_email_two_logins(client, db):
    tok = await program(client, db, "twoco")
    e = "both@two.example"
    op = await client.post("/auth/signup", json={"email": e, "password": "operator-pass", "name": "Op"})
    pt = await client.post("/partner/auth/signup", json={"email": e, "password": "partner-pass", "name": "Pat", "next": "/join/twoco"})
    assert op.status_code == 200 and pt.status_code == 200, (op.text, pt.text)
    assert op.json()["user"]["id"] != pt.json()["user"]["id"]
    assert (await db.partners.find_one({"email": e}))["_id"].startswith("ptn_")
    # Each password opens only its own side.
    assert (await client.post("/auth/login", json={"email": e, "password": "operator-pass"})).status_code == 200
    assert (await client.post("/auth/login", json={"email": e, "password": "partner-pass"})).status_code == 401
    assert (await client.post("/partner/auth/login", json={"email": e, "password": "partner-pass"})).status_code == 200
    assert (await client.post("/partner/auth/login", json={"email": e, "password": "operator-pass"})).status_code == 401
    # And each session only its own side.
    ptok, otok = pt.json()["token"], op.json()["token"]
    assert (await client.get("/auth/me", headers=auth(ptok))).status_code == 401
    assert (await client.get("/partner/auth/me", headers=auth(otok))).status_code == 401
    await db.partners.update_one({"email": e}, {"$set": {"email_verified": True}})
    a = (await client.post("/programs/twoco/join", json={}, headers=auth(ptok))).json()
    stored = await db.affiliates.find_one({"_id": a["id"]})
    assert stored["user_id"] == pt.json()["user"]["id"]
    assert (await client.get("/partner/auth/me", headers=auth(ptok))).json()["affiliations"] == 1
    assert (await client.post("/programs/twoco/join", json={}, headers=auth(otok))).status_code == 401
    assert (await client.get("/merchant", headers=auth(tok))).status_code == 200


async def test_sessions_from_before_the_split_keep_working(client, db):
    await program(client, db, "legacyco")
    # As the migration leaves it: the users record copied to partners under the same id.
    doc = {"_id": "usr_legacyaff1", "email": "old@legacy.example", "name": "Old", "password_hash": hash_password("old-password"), "email_verified": True, "session_gen": 2, "ip_hashes": [], "created_at": datetime.now(UTC)}
    await db.users.insert_one(dict(doc))
    await db.partners.insert_one(dict(doc))
    token = legacy_token(doc["_id"], gen=2)
    assert (await client.get("/portal", headers=auth(token))).status_code == 200
    assert (await client.post("/programs/legacyco/join", json={}, headers=auth(token))).status_code == 200
    assert (await client.get("/partner/auth/me", headers=auth(token))).json()["user"]["email"] == "old@legacy.example"
    # A reset since then still signs it out.
    assert (await client.get("/portal", headers=auth(legacy_token(doc["_id"], gen=1)))).status_code == 401
    # After cleanup (no users record) the dashboard side doesn't know it; the portal still does.
    await db.users.delete_one({"_id": doc["_id"]})
    assert (await client.get("/auth/me", headers=auth(token))).status_code == 401
    assert (await client.get("/portal", headers=auth(token))).status_code == 200


async def test_an_affiliates_leftover_users_record_is_not_an_operator(client, db):
    doc = {"_id": "usr_leftover1", "email": "left@over.example", "name": "Lefty", "password_hash": hash_password("their-password"), "email_verified": True, "ip_hashes": [], "created_at": datetime.now(UTC)}
    await db.users.insert_one(dict(doc))
    await db.partners.insert_one(dict(doc))
    assert (await client.post("/auth/login", json={"email": doc["email"], "password": "their-password"})).status_code == 401
    assert (await client.post("/partner/auth/login", json={"email": doc["email"], "password": "their-password"})).status_code == 200
    await client.post("/auth/password/forgot", json={"email": doc["email"]})
    assert not await db.emails.find_one({"to": doc["email"], "kind": "password_reset"})
    # Signing up for the dashboard makes a new operator; the affiliate login is untouched.
    r = await client.post("/auth/signup", json={"email": doc["email"], "password": "new-operator", "name": "Lefty"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] != doc["_id"]
    assert (await db.partners.find_one({"_id": doc["_id"]}))["password_hash"] == doc["password_hash"]
    assert (await client.post("/partner/auth/login", json={"email": doc["email"], "password": "their-password"})).status_code == 200


async def test_links_emailed_before_the_split(client, db):
    now = datetime.now(UTC)
    # Someone who runs a program and also promotes one: one record then, two now.
    await program(client, db, "dualco")
    owner = await db.users.find_one({"email": "owner@dualco.example"})
    h = sha256("reset-token-from-before-the-split-0001")
    pending = {"reset_token_hash": h, "reset_expires_at": now + timedelta(hours=1)}
    await db.users.update_one({"_id": owner["_id"]}, {"$set": pending})
    await db.partners.insert_one({k: v for k, v in owner.items()} | pending)
    r = await client.post("/auth/password/reset", json={"token": "reset-token-from-before-the-split-0001", "password": "brand-new-pass"})
    assert r.status_code == 200, r.text
    # It reset the one password both logins shared, as it would have before.
    assert (await client.post("/auth/login", json={"email": owner["email"], "password": "brand-new-pass"})).status_code == 200
    assert (await client.post("/partner/auth/login", json={"email": owner["email"], "password": "brand-new-pass"})).status_code == 200

    # An affiliate-only leftover: the dashboard side turns the link down, the portal takes it.
    doc = {"_id": "usr_leftover2", "email": "link@over.example", "name": "Link", "ip_hashes": [], "created_at": now, "verify_token_hash": sha256("verify-token-from-before-0000001"), "verify_expires_at": now + timedelta(days=1), "verify_next": "/a"}
    await db.users.insert_one(dict(doc))
    await db.partners.insert_one(dict(doc))
    assert (await client.post("/auth/verify", json={"token": "verify-token-from-before-0000001"})).status_code == 400
    r = await client.post("/partner/auth/verify", json={"token": "verify-token-from-before-0000001"})
    assert r.status_code == 200 and r.json()["next"] == "/a"
    assert (await db.partners.find_one({"_id": doc["_id"]}))["email_verified"] is True


async def test_partner_reset_and_claim_send_the_same_emails(client, db):
    e = "pat@reset.example"
    old = (await client.post("/partner/auth/signup", json={"email": e, "password": "first-password", "name": "Pat"})).json()["token"]
    mail = await db.emails.find_one({"to": e, "kind": "verify_email"})
    assert mail["subject"] == "Confirm your email for Kickrail"
    assert (await client.post("/partner/auth/password/forgot", json={"email": e})).json() == {"ok": True}
    mail = await db.emails.find_one({"to": e, "kind": "password_reset"})
    assert mail["subject"] == "Reset your Kickrail password"
    token = await latest_link(db, e, "password_reset")
    # Only the portal side knows this person.
    assert (await client.post("/auth/password/reset", json={"token": token, "password": "second-password"})).status_code == 400
    r = await client.post("/partner/auth/password/reset", json={"token": token, "password": "second-password"})
    assert r.status_code == 200
    assert (await client.get("/partner/auth/me", headers=auth(old))).status_code == 401
    me = (await client.get("/partner/auth/me", headers=auth(r.json()["token"]))).json()
    assert me["user"]["email_verified"] is True
    assert not await db.users.find_one({"email": e})
