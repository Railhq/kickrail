"""Operators signing in with Railhq accounts, against tests/railhq_fake.py (a stand-in for
accounts.getrailhq.com). Affiliates never go there."""

import json
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.routers import railhq

from .railhq_fake import FakeRailhq


@pytest.fixture
def fake(monkeypatch):
    f = FakeRailhq("kickrail")
    s = get_settings()
    monkeypatch.setattr(s, "railhq_issuer", f.issuer)
    monkeypatch.setattr(s, "railhq_client_id", "kickrail")
    monkeypatch.setattr(s, "railhq_client_secret", "secret")
    railhq.set_transport(f.transport)
    yield f
    railhq.set_transport(None)


def email() -> str:
    return f"r{secrets.token_hex(4)}@example.com"


def auth(token: str) -> dict:
    return {"authorization": f"Bearer {token}"}


async def local_operator(client, db, monkeypatch, verified=True, program=False) -> dict:
    """Someone who signed up before Railhq sign-in was switched on."""
    s = get_settings()
    issuer = s.railhq_issuer
    monkeypatch.setattr(s, "railhq_issuer", "")
    try:
        e = email()
        r = await client.post("/auth/signup", json={"email": e, "password": "password123", "name": "Lou"})
        assert r.status_code == 200, r.text
        if verified:
            await db.users.update_one({"email": e}, {"$set": {"email_verified": True}})
        out = {"email": e, "uid": r.json()["user"]["id"], "token": r.json()["token"]}
        if program:
            m = (await client.post("/merchant", json={"name": "Lou Co", "website": "https://lou.example"}, headers=auth(out["token"]))).json()
            out["merchant_id"] = m["merchant"]["id"]
        return out
    finally:
        monkeypatch.setattr(s, "railhq_issuer", issuer)


async def sso(client, fake, sub, next_path="/dashboard") -> dict:
    """Start + the browser at Railhq + callback."""
    st = (await client.post("/auth/railhq/start", json={"next": next_path})).json()
    q = {k: v[0] for k, v in parse_qs(urlparse(st["url"]).query).items()}
    nonce = railhq.client().read_flow(st["flow"], get_settings().app_secret)["n"]
    return await client.post("/auth/railhq/callback", json={"code": fake.code_for(sub, nonce), "state": q["state"], "flow": st["flow"]})


async def test_off_by_default(client, db, monkeypatch):
    assert (await client.get("/auth/railhq")).json() == {"railhq": False, "issuer": None}
    assert (await client.post("/auth/railhq/start", json={})).status_code == 404
    assert (await client.post("/railhq/events", content="x")).status_code == 404
    a = await local_operator(client, db, monkeypatch)
    r = await client.post("/auth/login", json={"email": a["email"], "password": "password123"})
    assert r.status_code == 200 and "railhq_handoff" not in r.json() and "rsid" not in str(r.json())
    assert (await client.post("/auth/logout", headers=auth(r.json()["token"]))).json() == {"redirect": None}


async def test_signup_makes_a_railhq_account(client, db, fake):
    assert (await client.get("/auth/railhq")).json() == {"railhq": True, "issuer": fake.issuer}
    e = email()
    r = await client.post("/auth/signup", json={"email": e, "password": "password123", "name": "Ray", "next": "/onboarding"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["railhq_handoff"].startswith(f"{fake.issuer}/handoff?token=hof_") and j["railhq_flow"]
    assert "client_id%3Dkickrail" in j["railhq_handoff"]
    u = await db.users.find_one({"email": e})
    assert u["railhq_id"] == fake.by_email(e)["sub"] and "password_hash" not in u
    # Railhq sends the confirmation email, not Kickrail.
    assert not await db.emails.find_one({"to": e, "kind": "verify_email"})
    assert (await client.get("/auth/me", headers=auth(j["token"]))).status_code == 200
    fake.add_user(other := email())
    r = await client.post("/auth/signup", json={"email": other, "password": "password123", "name": "Ray"})
    assert r.status_code == 409 and "Railhq account (used for Seorail)" in r.json()["detail"]
    assert not await db.users.find_one({"email": other})


async def test_login_links_and_imports(client, db, fake, monkeypatch):
    # 404 at Railhq: the local password is right, so the hash moves over as is.
    a = await local_operator(client, db, monkeypatch)
    old_hash = (await db.users.find_one({"_id": a["uid"]}))["password_hash"]
    assert (await client.post("/auth/login", json={"email": a["email"], "password": "wrong-one"})).status_code == 401
    assert not fake.by_email(a["email"])
    r = await client.post("/auth/login", json={"email": a["email"], "password": "password123"})
    assert r.status_code == 200 and r.json()["railhq_handoff"]
    moved = fake.by_email(a["email"])
    assert moved["_hash"] == old_hash and moved["email_verified"] is True
    assert (await db.users.find_one({"_id": a["uid"]}))["railhq_id"] == moved["sub"]
    # Linked now: Railhq's password decides.
    assert (await client.post("/auth/login", json={"email": a["email"], "password": "password123"})).status_code == 200

    # 200 at Railhq for an existing local user with a confirmed Railhq address: linked.
    b = await local_operator(client, db, monkeypatch)
    fake.add_user(b["email"], "railhq-pass")
    r = await client.post("/auth/login", json={"email": b["email"], "password": "railhq-pass"})
    assert r.status_code == 200 and r.json()["user"]["id"] == b["uid"]
    assert (await db.users.find_one({"_id": b["uid"]}))["railhq_id"] == fake.by_email(b["email"])["sub"]


async def test_wrong_railhq_password_but_right_local_one(client, db, fake, monkeypatch):
    a = await local_operator(client, db, monkeypatch)
    fake.add_user(a["email"], "a-different-pass")
    r = await client.post("/auth/login", json={"email": a["email"], "password": "password123"})
    assert r.status_code == 200 and r.json()["railhq_note"].startswith("This email already has a Railhq account")
    assert "railhq_handoff" not in r.json()
    assert "railhq_id" not in await db.users.find_one({"_id": a["uid"]})


async def test_unconfirmed_railhq_address_cannot_take_an_account(client, db, fake, monkeypatch):
    victim = await local_operator(client, db, monkeypatch, program=True)
    # Anyone can make a Railhq account for any address.
    fake.add_user(victim["email"], "attacker-pass", verified=False)
    r = await client.post("/auth/login", json={"email": victim["email"], "password": "attacker-pass"})
    assert r.status_code == 403 and "confirm your email first" in r.json()["detail"]
    sub = fake.by_email(victim["email"])["sub"]
    assert (await sso(client, fake, sub)).status_code == 403
    assert "railhq_id" not in await db.users.find_one({"_id": victim["uid"]})
    # Once the address is confirmed at Railhq it's the owner's, and links.
    fake.by_email(victim["email"])["email_verified"] = True
    r = await client.post("/auth/login", json={"email": victim["email"], "password": "attacker-pass"})
    assert r.status_code == 200 and r.json()["user"]["id"] == victim["uid"]


async def test_affiliates_never_reach_railhq(client, db, fake):
    e = email()
    r = await client.post("/partner/auth/signup", json={"email": e, "password": "partner-pass", "name": "Pat"})
    assert r.status_code == 200 and "railhq_handoff" not in r.json()
    assert (await client.post("/partner/auth/login", json={"email": e, "password": "partner-pass"})).status_code == 200
    # On the dashboard form the affiliate's email isn't sent to Railhq; the web app tries the portal next.
    assert (await client.post("/auth/login", json={"email": e, "password": "partner-pass"})).status_code == 401
    await client.post("/auth/password/forgot", json={"email": e})
    await client.post("/partner/auth/password/forgot", json={"email": e})
    assert not [c for c in fake.calls if e in json.dumps(c)]
    assert not fake.by_email(e)


async def test_start_callback_and_login_required(client, db, fake, monkeypatch):
    who = fake.add_user(e := email(), name="Sia")
    r = await sso(client, fake, who["sub"], "/dashboard/billing")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["next"] == "/dashboard/billing" and j["user"]["email"] == e
    assert (await client.get("/auth/me", headers=auth(j["token"]))).status_code == 200
    # Silent check: the web app asks with prompt=none.
    st = (await client.post("/auth/railhq/start", json={"next": "/home", "prompt": "none"})).json()
    assert "prompt=none" in st["url"]
    # A bad state never signs anyone in.
    st = (await client.post("/auth/railhq/start", json={})).json()
    nonce = railhq.client().read_flow(st["flow"], get_settings().app_secret)["n"]
    assert (await client.post("/auth/railhq/callback", json={"code": fake.code_for(who["sub"], nonce), "state": "forged", "flow": st["flow"]})).status_code == 400
    # Sign-out goes through Railhq for a Railhq session.
    out = (await client.post("/auth/logout", headers=auth(j["token"]))).json()["redirect"]
    assert out.startswith(f"{fake.issuer}/logout?") and "kickrail.test%2Flogin" in out


async def test_backchannel_logout_ends_the_session(client, db, fake):
    who = fake.add_user(email())
    tok = (await sso(client, fake, who["sub"])).json()["token"]
    import jwt as pyjwt

    sid = pyjwt.decode(tok, options={"verify_signature": False})["rsid"]
    r = await client.post("/railhq/backchannel", data={"logout_token": fake.logout_token(who["sub"], sid)})
    assert r.status_code == 200
    assert (await client.get("/auth/me", headers=auth(tok))).status_code == 401
    assert (await client.post("/railhq/backchannel", data={"logout_token": "nope"})).status_code == 400
    # Signed out everywhere (no sid): every session from before it.
    tok = (await sso(client, fake, who["sub"])).json()["token"]
    await client.post("/railhq/backchannel", data={"logout_token": fake.sign({"aud": "kickrail", "jti": "x1", "sub": who["sub"], "events": {"http://schemas.openid.net/event/backchannel-logout": {}}}, typ="logout+jwt")})
    assert (await client.get("/auth/me", headers=auth(tok))).status_code == 401


async def test_events_update_email_and_pass(client, db, fake):
    who = fake.add_user(email())
    tok = (await sso(client, fake, who["sub"])).json()["token"]
    m = (await client.post("/merchant", json={"name": "Passco", "website": "https://passco.example"}, headers=auth(tok))).json()["merchant"]
    # Off the trial, on the free plan.
    await db.merchants.update_one({"_id": m["id"]}, {"$set": {"plan": {"id": "free", "status": "active"}}})
    assert (await client.get("/merchant", headers=auth(tok))).json()["plan"]["id"] == "free"
    assert (await client.post("/railhq/events", content=fake.event("pass.updated", {"sub": who["sub"], "pass": True}))).status_code == 200
    plan = (await client.get("/merchant", headers=auth(tok))).json()["plan"]
    assert plan["id"] == "starter" and plan["source"] == "pass" and not plan["subscribed"]
    # A paid plan above it wins.
    await db.merchants.update_one({"_id": m["id"]}, {"$set": {"plan": {"id": "growth", "status": "active", "stripe_subscription": "sub_1"}}})
    assert (await client.get("/merchant", headers=auth(tok))).json()["plan"]["id"] == "growth"
    await db.merchants.update_one({"_id": m["id"]}, {"$set": {"plan": {"id": "free", "status": "active"}}})
    await client.post("/railhq/events", content=fake.event("pass.updated", {"sub": who["sub"], "pass": False}))
    assert (await client.get("/merchant", headers=auth(tok))).json()["plan"]["id"] == "free"

    # Email changed (and confirmed) at Railhq.
    new = email()
    fake.users[who["sub"]]["email"] = new
    assert (await client.post("/railhq/events", content=fake.event("user.updated", {"sub": who["sub"]}))).status_code == 200
    assert (await db.users.find_one({"railhq_id": who["sub"]}))["email"] == new
    # Unknown people and bad tokens.
    assert (await client.post("/railhq/events", content=fake.event("user.updated", {"sub": "usr_nobody"}))).status_code == 200
    assert (await client.post("/railhq/events", content="not-a-jwt")).status_code == 400
    # Deleted at Railhq: unlinked and signed out, programs kept.
    await client.post("/railhq/events", content=fake.event("user.deleted", {"sub": who["sub"]}))
    assert (await client.get("/auth/me", headers=auth(tok))).status_code == 401
    assert await db.merchants.find_one({"_id": m["id"]})


async def test_pass_follows_ownership(client, db, fake):
    who = fake.add_user(email())
    tok = (await sso(client, fake, who["sub"])).json()["token"]
    await client.post("/railhq/events", content=fake.event("pass.updated", {"sub": who["sub"], "pass": True}))
    m = (await client.post("/merchant", json={"name": "Newco", "website": "https://newco.example"}, headers=auth(tok))).json()["merchant"]
    assert (await db.merchants.find_one({"_id": m["id"]}))["railhq_pass"] is True
    mate = fake.add_user(email())
    mate_tok = (await sso(client, fake, mate["sub"])).json()["token"]
    mate_id = (await db.users.find_one({"railhq_id": mate["sub"]}))["_id"]
    await db.merchants.update_one({"_id": m["id"]}, {"$addToSet": {"member_ids": mate_id}})
    assert (await client.post("/merchant/team/owner", json={"user_id": mate_id}, headers=auth(tok))).status_code == 200
    assert (await db.merchants.find_one({"_id": m["id"]}))["railhq_pass"] is False
    assert (await client.get("/merchant", headers=auth(mate_tok))).json()["owner_id"] == mate_id


async def test_mcp_through_the_gateway(client, db, fake):
    who = fake.add_user(email())
    tok = (await sso(client, fake, who["sub"])).json()["token"]
    h = auth(tok)
    first = (await client.post("/merchant", json={"name": "Gate One", "website": "https://one.example"}, headers=h)).json()["merchant"]
    second = (await client.post("/merchant", json={"name": "Gate Two", "website": "https://two.example"}, headers=h)).json()["merchant"]
    gw = {"authorization": f"Bearer {fake.access_token(who['sub'])}"}
    call = lambda method, headers, params=None: client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=headers)  # noqa: E731
    r = (await call("railhq/workspaces", gw)).json()["result"]
    assert r == {"workspaces": [{"id": first["id"], "name": "Gate One", "role": "owner"}, {"id": second["id"], "name": "Gate Two", "role": "owner"}]}
    status = lambda r: r.json()["result"]["structuredContent"]  # noqa: E731
    assert status(await call("tools/call", gw, {"name": "setup_status", "arguments": {}}))["program"]["name"] == "Gate One"
    pick = gw | {"x-railhq-workspace": second["id"]}
    assert status(await call("tools/call", pick, {"name": "setup_status", "arguments": {}}))["program"]["name"] == "Gate Two"
    # Someone else's program in the header: their own default instead.
    other = (await db.merchants.find_one({"_id": {"$nin": [first["id"], second["id"]]}}, {"_id": 1}))["_id"]
    assert status(await call("tools/call", gw | {"x-railhq-workspace": other}, {"name": "setup_status", "arguments": {}}))["program"]["name"] == "Gate One"
    # Tokens for another app, or for someone who never used Kickrail, don't open anything.
    assert (await call("tools/list", {"authorization": f"Bearer {fake.access_token(who['sub'], aud='seorail')}"})).status_code == 401
    stranger = fake.add_user(email())
    assert (await call("tools/list", {"authorization": f"Bearer {fake.access_token(stranger['sub'])}"})).status_code == 401


async def test_mcp_gateway_off_by_default(client, db):
    assert (await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={"authorization": "Bearer eyJhbGciOi.fake.token"})).status_code == 401


async def _pass_holder(client, db, fake, programs: int, tier: str = "pass") -> tuple[dict, dict, list[str]]:
    """An operator owning `programs` programs (oldest first, all on Free), then given a Pass."""
    from datetime import UTC, datetime, timedelta

    who = fake.add_user(email())
    h = auth((await sso(client, fake, who["sub"])).json()["token"])
    ids = []
    for i in range(programs):
        m = (await client.post("/merchant", json={"name": f"Tier {i}", "website": f"https://t{i}.example"}, headers=h)).json()["merchant"]
        await db.merchants.update_one({"_id": m["id"]}, {"$set": {"plan": {"id": "free", "status": "active"}, "created_at": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)}})
        ids.append(m["id"])
    assert (await client.post("/railhq/events", content=fake.event("pass.updated", fake.set_pass(who["sub"], tier)))).status_code == 200
    return who, h, ids


async def _covered(db, ids: list[str]) -> list[str]:
    return [i for i in ids if (await db.merchants.find_one({"_id": i}))["railhq_pass"]]


async def _plan(client, h, mid) -> dict:
    return (await client.get("/merchant", headers=h | {"x-kickrail-program": mid})).json()["plan"]


async def test_pass_covers_only_the_oldest(client, db, fake):
    who, h, ids = await _pass_holder(client, db, fake, 3)
    assert (await db.users.find_one({"railhq_id": who["sub"]}))["railhq_pass_workspaces"] == 1
    assert await _covered(db, ids) == ids[:1]
    assert (await _plan(client, h, ids[0]))["source"] == "pass"
    # Uncovered falls back to its own plan, and billing says why.
    assert (await _plan(client, h, ids[1]))["id"] == "free"
    b = (await client.get("/merchant/billing", headers=h | {"x-kickrail-program": ids[1]})).json()
    assert b["railhq_pass"] == {"workspaces": 1, "covered": False}
    got = (await client.get("/railhq/pass-workspaces", headers=h)).json()
    assert got["workspaces"] == 1 and got["used"] == 1 and [p["covered"] for p in got["programs"]] == [True, False, False]


async def test_team_pass_covers_three(client, db, fake):
    who, h, ids = await _pass_holder(client, db, fake, 4, "team")
    assert await _covered(db, ids) == ids[:3]
    assert [(await _plan(client, h, i))["id"] for i in ids] == ["starter", "starter", "starter", "free"]
    # The ID token carries the count too.
    await sso(client, fake, who["sub"])
    assert (await db.users.find_one({"railhq_id": who["sub"]}))["railhq_pass_workspaces"] == 3


async def test_pick_moves_coverage(client, db, fake):
    who, h, ids = await _pass_holder(client, db, fake, 3)
    r = await client.put("/railhq/pass-workspaces", json={"workspace_ids": [ids[2]]}, headers=h)
    assert r.status_code == 200, r.text
    assert await _covered(db, ids) == [ids[2]]
    assert (await _plan(client, h, ids[0]))["id"] == "free" and (await _plan(client, h, ids[2]))["source"] == "pass"
    # An upgrade fills the new slots from the oldest, keeping the pick.
    await client.post("/railhq/events", content=fake.event("pass.updated", fake.set_pass(who["sub"], "team")))
    assert set(await _covered(db, ids)) == set(ids)


async def test_picks_over_the_count_or_not_owned_are_refused(client, db, fake):
    who, h, ids = await _pass_holder(client, db, fake, 3)
    assert (await client.put("/railhq/pass-workspaces", json={"workspace_ids": ids[1:]}, headers=h)).status_code == 400
    # A member who doesn't own the program can't put it on their own Pass.
    mate = fake.add_user(email())
    mh = auth((await sso(client, fake, mate["sub"])).json()["token"])
    mate_id = (await db.users.find_one({"railhq_id": mate["sub"]}))["_id"]
    await db.merchants.update_one({"_id": ids[1]}, {"$addToSet": {"member_ids": mate_id}})
    await client.post("/railhq/events", content=fake.event("pass.updated", fake.set_pass(mate["sub"], "pass")))
    assert (await client.put("/railhq/pass-workspaces", json={"workspace_ids": [ids[1]]}, headers=mh)).status_code == 403
    assert (await client.get("/merchant/billing", headers=mh | {"x-kickrail-program": ids[1]})).json()["railhq_pass"] is None
    # No Pass at all.
    await client.post("/railhq/events", content=fake.event("pass.updated", fake.set_pass(mate["sub"], None)))
    assert (await client.put("/railhq/pass-workspaces", json={"workspace_ids": []}, headers=mh)).status_code == 400
    assert await _covered(db, ids) == ids[:1]


async def test_pass_removed_covers_none(client, db, fake):
    who, h, ids = await _pass_holder(client, db, fake, 2, "team")
    assert await _covered(db, ids) == ids
    await client.post("/railhq/events", content=fake.event("pass.updated", fake.set_pass(who["sub"], None)))
    assert await _covered(db, ids) == []
    assert (await db.users.find_one({"railhq_id": who["sub"]}))["railhq_pass_workspaces"] == 0
    assert [(await _plan(client, h, i))["id"] for i in ids] == ["free", "free"]


async def test_losing_a_covered_program_frees_the_slot(client, db, fake):
    from app.services import pass_coverage

    who, h, ids = await _pass_holder(client, db, fake, 3)
    uid = (await db.users.find_one({"railhq_id": who["sub"]}))["_id"]
    await client.put("/railhq/pass-workspaces", json={"workspace_ids": [ids[1]]}, headers=h)
    assert await _covered(db, ids) == [ids[1]]
    # Deleted (there's no delete route yet; anything that deletes calls refresh): the oldest left takes the slot.
    await db.merchants.delete_one({"_id": ids[1]})
    await pass_coverage.refresh(db, uid)
    assert await _covered(db, [ids[0], ids[2]]) == [ids[0]]
    # Handed to a teammate: the old owner's next oldest takes it.
    mate = fake.add_user(email())
    await sso(client, fake, mate["sub"])
    mate_id = (await db.users.find_one({"railhq_id": mate["sub"]}))["_id"]
    await db.merchants.update_one({"_id": ids[0]}, {"$addToSet": {"member_ids": mate_id}})
    assert (await client.post("/merchant/team/owner", json={"user_id": mate_id}, headers=h | {"x-kickrail-program": ids[0]})).status_code == 200
    assert await _covered(db, [ids[0], ids[2]]) == [ids[2]]


async def test_old_boolean_pass_counts_as_one(client, db, fake):
    from app.services import pass_coverage

    who, h, ids = await _pass_holder(client, db, fake, 2)
    uid = (await db.users.find_one({"railhq_id": who["sub"]}))["_id"]
    # Before tiers: the boolean only, and every owned program marked.
    await db.users.update_one({"_id": uid}, {"$unset": {"railhq_pass_workspaces": ""}})
    await db.merchants.update_many({"_id": {"$in": ids}}, {"$set": {"railhq_pass": True}})
    await pass_coverage.backfill(db)
    assert await _covered(db, ids) == ids[:1]
    # A pass.updated without a count (an older accounts service) is a one-workspace Pass.
    await client.post("/railhq/events", content=fake.event("pass.updated", {"sub": who["sub"], "pass": True}))
    assert (await db.users.find_one({"_id": uid}))["railhq_pass_workspaces"] == 1
