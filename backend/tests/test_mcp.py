"""The MCP endpoint a coding agent uses to set a program up."""

from types import SimpleNamespace

import pytest

from app import deps
from app.main import app
from app.routers import mcp
from app.services.rewardful_import import RewardfulError


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


@pytest.fixture(scope="module")
async def program(client, db):
    owner = await signup(client, db, "owner@mcpco.example", "Mia")
    r = (await client.post("/merchant", json={"name": "Mcpco", "website": "https://mcpco.example"}, headers=auth(owner))).json()
    return {"id": r["merchant"]["id"], "key": r["secret_key"], "public_key": r["merchant"]["public_key"], "session": owner}


class Agent:
    def __init__(self, client, key):
        self.client, self.key, self.n = client, key, 0

    async def rpc(self, method, params=None):
        self.n += 1
        r = await self.client.post("/mcp", json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}, headers=auth(self.key))
        assert r.status_code == 200, r.text
        return r.json()

    async def call(self, tool, **args):
        res = (await self.rpc("tools/call", {"name": tool, "arguments": args}))["result"]
        return res, res.get("structuredContent")


async def test_auth_and_transport(client, program):
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and "sk_kr_" in r.json()["error"]["message"]
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=auth("sk_kr_wrong"))
    assert r.status_code == 401
    # A dashboard session is not an MCP key.
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=auth(program["session"]))
    assert r.status_code == 401
    assert (await client.get("/mcp", headers=auth(program["key"]))).status_code == 405

    agent = Agent(client, program["key"])
    init = (await agent.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}))["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"] and "Mcpco" in init["instructions"]
    assert (await agent.rpc("initialize", {"protocolVersion": "1999-01-01"}))["result"]["protocolVersion"] == mcp.PROTOCOLS[0]
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=auth(program["key"]))
    assert r.status_code == 202 and not r.content
    tools = {t["name"]: t for t in (await agent.rpc("tools/list"))["result"]["tools"]}
    assert {"setup_status", "connect_stripe", "verify_install", "create_campaign", "start_rewardful_import"} <= set(tools)
    assert tools["add_affiliate"]["inputSchema"]["type"] == "object" and "send_welcome_email" in tools["add_affiliate"]["inputSchema"]["required"]
    assert (await agent.rpc("tools/call", {"name": "nope"}))["error"]["code"] == -32602
    assert (await agent.rpc("resources/list"))["error"]["code"] == -32601
    r = await client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}], headers=auth(program["key"]))
    assert r.json() == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    r = await client.post("/mcp", content=b"{nope", headers=auth(program["key"]))
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700


async def test_setup_flow(client, db, program, monkeypatch):
    agent = Agent(client, program["key"])
    _, s = await agent.call("setup_status")
    assert s["next_step"] == "connect_stripe" and s["program"]["website"] == "https://mcpco.example" and s["join_page"].endswith("/join/mcpco")

    # Without one-click Connect configured, the link is the Settings page.
    _, c = await agent.call("connect_stripe")
    assert not c["connected"] and c["url"].endswith("/dashboard/settings#stripe")
    real = mcp.get_settings()
    monkeypatch.setattr(mcp, "get_settings", lambda: SimpleNamespace(stripe_oauth=True, public_url=real.public_url))
    _, c = await agent.call("connect_stripe")
    assert c["url"] == f"https://kickrail.test/dashboard/stripe/connect?program={program['id']}"
    monkeypatch.undo()
    await db.merchants.update_one({"_id": program["id"]}, {"$set": {"stripe": {"oauth": True, "account_id": "acct_x", "account_name": "Mcpco Inc", "livemode": False, "connected_at": None}}})
    _, c = await agent.call("connect_stripe")
    assert c["connected"] and c["account_name"] == "Mcpco Inc"

    _, i = await agent.call("get_install_instructions", framework="nextjs-app")
    assert program["public_key"] in i["script_tag"] and "app/layout.tsx" in i["where"] and "/api/v1/referrals" in i["server_side_signup"]["request"]
    res, _ = await agent.call("get_install_instructions", framework="cobol")
    assert res["isError"] and "framework" in res["content"][0]["text"]

    # The script records that it loaded, at most hourly.
    await client.get(f"/kr.js?k={program['public_key']}", headers={"referer": "https://app.mcpco.example/signup"})
    first = (await db.merchants.find_one({"_id": program["id"]}))["tracking"]
    await client.get(f"/kr.js?k={program['public_key']}", headers={"referer": "https://other.example/"})
    assert (await db.merchants.find_one({"_id": program["id"]}))["tracking"] == first
    _, s = await agent.call("setup_status")
    assert s["script"]["last_loaded_on"] == "app.mcpco.example" and s["next_step"] == "test_referral"

    async def page(m, url):
        return url, f'<script async src="https://kickrail.test/api/kr.js?k={m["public_key"]}"></script>'

    monkeypatch.setattr(mcp, "fetch_page", page)
    _, v = await agent.call("verify_install")
    assert v["script_in_page_html"] is True and v["diagnosis"].startswith("Installed") and "test_link" not in v and "add_affiliate" in v["how_to_test"]

    res, _ = await agent.call("add_affiliate", email="me@mcpco.example", name="Mia Test")
    assert res["isError"] and "send_welcome_email" in res["content"][0]["text"]
    _, a = await agent.call("add_affiliate", email="me@mcpco.example", name="Mia Test", send_welcome_email=False)
    assert a["created"] and a["status"] == "approved"
    assert not await db.outbox.find_one({"to": "me@mcpco.example"})
    _, v = await agent.call("verify_install")
    assert v["test_link"] == f"https://mcpco.example/?via={a['token']}&kr_test=1"

    await client.post("/track/click", json={"key": program["public_key"], "id": "kr_" + "a" * 20, "token": a["token"], "test": True})
    _, v = await agent.call("verify_install")
    assert v["test_clicks_last_24h"] == 1
    _, s = await agent.call("setup_status")
    assert s["next_step"] is None and s["counts"]["test_clicks"] == 1

    _, aff = await agent.call("list_affiliates", status="approved")
    assert [x["id"] for x in aff["data"]] == [a["id"]]
    res, _ = await agent.call("list_referrals", status="bogus")
    assert res["isError"]


async def test_campaigns_and_program(client, db, program):
    agent = Agent(client, program["key"])
    _, c = await agent.call("create_campaign", name="Launch", rule_type="percent", percent=40, duration_mode="months", months=6)
    assert c["description"] and c["hold_days"] == 30 and c["min_payout_cents"] == 5000 and not c["is_default"]
    res, _ = await agent.call("create_campaign", name="Bad", rule_type="flat", duration_mode="once")
    assert res["isError"] and "flat" in res["content"][0]["text"]

    # Partial updates keep everything else.
    _, u = await agent.call("update_campaign", campaign_id=c["id"], percent=25, make_default=True)
    assert u["rule"] == {"type": "percent", "bps": 2500} and u["duration"] == {"mode": "months", "months": 6} and u["name"] == "Launch" and u["is_default"]
    _, u = await agent.call("update_campaign", campaign_id=c["id"], duration_mode="forever")
    assert u["duration"] == {"mode": "forever"} and u["rule"]["bps"] == 2500
    _, u = await agent.call("update_campaign", campaign_id=c["id"], rule_type="flat", flat_cents=1500)
    assert u["rule"] == {"type": "flat", "cents": 1500, "currency": "usd"}
    _, lst = await agent.call("list_campaigns")
    assert [x["is_default"] for x in lst["campaigns"]] == [False, True]
    res, _ = await agent.call("update_campaign", campaign_id="cmp_nope", name="x")
    assert res["isError"] and "not found" in res["content"][0]["text"]

    _, p = await agent.call("update_program", cookie_days=90, auto_approve=False)
    assert p["settings"]["cookie_days"] == 90 and p["settings"]["auto_approve"] is False and p["name"] == "Mcpco"
    res, _ = await agent.call("update_program", website="not a url")
    assert res["isError"]

    # Managing affiliates over MCP follows the API plan gate.
    await db.merchants.update_one({"_id": program["id"]}, {"$set": {"plan": {"id": "free"}}})
    res, _ = await agent.call("list_commissions")
    assert res["isError"] and "plan" in res["content"][0]["text"]
    _, s = await agent.call("setup_status")
    assert s["program"]["plan"] == "Free"


async def test_rewardful_import_over_mcp(client, db, program):
    class Bad:
        def __init__(self, secret):
            pass

        async def get(self, path, params):
            raise RewardfulError("Rewardful didn't accept that API secret")

        async def __aexit__(self, *exc):
            pass

    app.dependency_overrides[deps.rewardful_client] = lambda: Bad
    try:
        agent = Agent(client, program["key"])
        res, _ = await agent.call("start_rewardful_import", api_secret="sk_rewardful_secret_1")
        assert res["isError"] and "API secret" in res["content"][0]["text"] and "sk_rewardful_secret_1" not in res["content"][0]["text"]
        _, st = await agent.call("import_status")
        assert st == {"import": None}
    finally:
        app.dependency_overrides.pop(deps.rewardful_client, None)


async def test_fetch_page_stays_on_the_website():
    m = {"website": "https://mcpco.example", "public_key": "pk"}
    with pytest.raises(ValueError, match="mcpco.example"):
        await mcp.fetch_page(m, "https://evil.example/")
    with pytest.raises(ValueError, match="mcpco.example"):
        await mcp.fetch_page(m, "file:///etc/passwd")
    with pytest.raises(ValueError, match="public address"):
        await mcp.fetch_page({"website": "http://localhost", "public_key": "pk"}, "http://localhost/")


async def test_portal_domains(client, db, program, monkeypatch):
    from app.routers import merchant as mr

    dns = {"ok": False}
    monkeypatch.setattr(mr, "_cname_ok", lambda host: (dns["ok"], "verified" if dns["ok"] else f"{host} does not exist in DNS yet"))

    async def https(host):
        return True, "HTTPS is working"

    monkeypatch.setattr(mr, "_https_ok", https)
    await db.merchants.update_one({"_id": program["id"]}, {"$set": {"plan": {"id": "starter"}}})
    agent = Agent(client, program["key"])
    _, lst = await agent.call("list_portal_domains")
    assert lst["domains"] == [] and lst["plan_allows"] == 1

    _, d = await agent.call("add_portal_domain", host="https://Partners.Mcpco.example/")
    assert d["host"] == "partners.mcpco.example" and d["status"] == "not_verified" and d["primary"]
    assert d["dns_record"] == {"type": "CNAME", "name": "partners.mcpco.example", "value": "portals.kickrail.com"} and "check_portal_domain" in d["next"]
    res, _ = await agent.call("add_portal_domain", host="more.mcpco.example")
    assert res["isError"] and "plan" in res["content"][0]["text"].lower()

    dns["ok"] = True
    _, d = await agent.call("check_portal_domain", host="partners.mcpco.example")
    assert d["status"] == "live" and d["next"].startswith("Live")
    _, s = await agent.call("setup_status")
    assert s["portal_domains"] == [{"host": "partners.mcpco.example", "status": "live", "primary": True}] and s["join_page"].startswith("https://partners.mcpco.example")
    res, _ = await agent.call("check_portal_domain", host="nope.mcpco.example")
    assert res["isError"]

    # The same over the REST API (Growth and up).
    h = auth(program["key"])
    assert (await client.get("/v1/domains", headers=h)).status_code == 402
    await db.merchants.update_one({"_id": program["id"]}, {"$set": {"plan": {"id": "growth"}}})
    r = await client.get("/v1/domains", headers=h)
    assert [x["status"] for x in r.json()["data"]] == ["live"]
    r = await client.post("/v1/domains", json={"host": "eu.mcpco.example"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "live" and not r.json()["primary"]
    r = await client.post("/v1/domains/eu.mcpco.example/primary", headers=h)
    assert {x["host"]: x["primary"] for x in r.json()["data"]} == {"partners.mcpco.example": False, "eu.mcpco.example": True}
    r = await client.post("/v1/domains/eu.mcpco.example/verify", headers=h)
    assert r.json()["status"] == "live"
    assert (await client.delete("/v1/domains/eu.mcpco.example", headers=h)).json() == {"deleted": True, "host": "eu.mcpco.example"}
    r = await client.get("/v1/domains", headers=h)
    assert [(x["host"], x["primary"]) for x in r.json()["data"]] == [("partners.mcpco.example", True)]
    assert (await client.delete("/v1/domains/eu.mcpco.example", headers=h)).status_code == 404
