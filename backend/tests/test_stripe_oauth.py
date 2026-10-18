"""One-click "Connect with Stripe" (Connect OAuth) and leads the script captures from forms on its own."""

import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from app import deps
from app.main import app

from .conftest import sign


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


class FakeOAuth:
    def __init__(self):
        self.deauthorized: list[str] = []

    def authorize_url(self, state, redirect_uri, email=None):
        return f"https://connect.stripe.test/oauth/authorize?state={state}&redirect_uri={redirect_uri}"

    async def token(self, code):
        if code == "bad":
            raise RuntimeError("invalid code")
        return {"account_id": f"acct_{code}", "livemode": False}

    async def deauthorize(self, account_id):
        self.deauthorized.append(account_id)


class FakeAccount:
    def __init__(self, account_id):
        self.id = account_id

    async def account(self):
        return {"id": self.id, "name": "Oauthco"}


@pytest.fixture(scope="module")
def oauth():
    fake = FakeOAuth()
    app.dependency_overrides[deps.stripe_oauth] = lambda: fake
    app.dependency_overrides[deps.stripe_oauth_optional] = lambda: fake
    app.dependency_overrides[deps.merchant_account_client] = lambda: FakeAccount
    yield fake
    for d in (deps.stripe_oauth, deps.stripe_oauth_optional, deps.merchant_account_client):
        app.dependency_overrides.pop(d, None)


@pytest.fixture(scope="module")
async def prog(client, db):
    token = await signup(client, db, "owner@oauth.example", "Oli")
    r = await client.post("/merchant", json={"name": "Oauthco", "website": "https://oauthco.example"}, headers=auth(token))
    return {"token": token, "id": r.json()["merchant"]["id"]}


async def start(client, prog):
    url = (await client.get("/merchant/stripe/oauth", headers=auth(prog["token"]))).json()["url"]
    q = parse_qs(urlsplit(url).query)
    assert q["redirect_uri"] == ["https://kickrail.test/dashboard/stripe/callback"]
    return q["state"][0]


async def platform_event(client, account, type_, obj):
    event = {"id": f"evt_{secrets.token_hex(6)}", "type": type_, "account": account, "created": int(datetime.now(UTC).timestamp()), "data": {"object": obj}}
    payload = json.dumps(event)
    r = await client.post("/webhooks/platform", content=payload, headers={"stripe-signature": sign(payload, "whsec_platform"), "content-type": "application/json"})
    return r.json()["outcome"]


async def test_connect_with_stripe(client, db, prog, oauth):
    h = auth(prog["token"])
    state = await start(client, prog)
    assert (await client.post("/merchant/stripe/oauth", json={"code": "bad", "state": state}, headers=h)).status_code == 400
    assert (await client.post("/merchant/stripe/oauth", json={"code": "one", "state": "forged"}, headers=h)).status_code == 400
    # A state started by someone else can't be finished by this user.
    other = await signup(client, db, "other@oauth.example", "Ola")
    r = await client.post("/merchant/stripe/oauth", json={"code": "one", "state": state}, headers=auth(other))
    assert r.status_code == 400
    r = await client.post("/merchant/stripe/oauth", json={"code": "one", "state": state}, headers=h)
    s = r.json()["stripe"]
    assert r.status_code == 200 and s["mode"] == "oauth" and s["account_id"] == "acct_one" and s["livemode"] is False
    stored = (await db.merchants.find_one({"_id": prog["id"]}))["stripe"]
    assert "key_enc" not in stored and "webhook_secret_enc" not in stored
    # The same Stripe account can't feed two programs.
    await client.post("/merchant", json={"name": "Second", "website": "https://second.example"}, headers=auth(other))
    r = await client.post("/merchant/stripe/oauth", json={"code": "one", "state": await start(client, {"token": other})}, headers=auth(other))
    assert r.status_code == 409 and "Oauthco" in r.json()["detail"]


async def test_auto_leads_only_take_new_customers(client, db, prog, oauth, fakes):
    m = (await client.get("/merchant", headers=auth(prog["token"]))).json()
    aff_token = await signup(client, db, "aff@oauth.example", "Ava")
    aff = (await client.post("/programs/oauthco/join", json={}, headers=auth(aff_token))).json()
    token = (await db.affiliates.find_one({"_id": aff["id"]}))["token"]

    async def lead(email, auto=True):
        click = "kr_" + secrets.token_hex(10)
        await client.post("/track/click", content=json.dumps({"key": m["public_key"], "id": click, "token": token}))
        await client.post("/track/lead", content=json.dumps({"key": m["public_key"], "id": click, "email": email, "auto": auto}))
        return await db.referrals.find_one({"merchant_id": prog["id"], "email": email})

    def invoice(cid, email):
        return {
            "id": f"in_{secrets.token_hex(4)}", "customer": cid, "customer_email": email, "amount_paid": 10_000, "currency": "usd",
            "status_transitions": {"paid_at": int(datetime.now(UTC).timestamp())}, "lines": {"data": []},
        }

    old = await lead("old@buyer.example")
    assert old["auto"] is True
    fakes["merchant"].customer_times["cus_old"] = datetime.now(UTC) - timedelta(days=90)
    assert await platform_event(client, "acct_one", "invoice.paid", invoice("cus_old", "old@buyer.example")) == "no referral"
    old = await db.referrals.find_one({"_id": old["_id"]})
    assert "stripe_customer_id" not in old and any(f["kind"] == "existing_customer" for f in old["flags"])
    assert await db.commissions.count_documents({"referral_id": old["_id"]}) == 0

    new = await lead("new@buyer.example")
    fakes["merchant"].customer_times["cus_new"] = datetime.now(UTC)
    await platform_event(client, "acct_one", "invoice.paid", invoice("cus_new", "new@buyer.example"))
    new = await db.referrals.find_one({"_id": new["_id"]})
    assert new["stripe_customer_id"] == "cus_new" and new["status"] == "customer"
    assert await db.commissions.count_documents({"referral_id": new["_id"]}) == 1

    # A lead the merchant reported on purpose isn't held to the new-customer rule.
    told = await lead("told@buyer.example", auto=False)
    assert "auto" not in told
    fakes["merchant"].customer_times["cus_told"] = datetime.now(UTC) - timedelta(days=90)
    await platform_event(client, "acct_one", "invoice.paid", invoice("cus_told", "told@buyer.example"))
    assert (await db.referrals.find_one({"_id": told["_id"]}))["stripe_customer_id"] == "cus_told"

    # Events for accounts no program connected are left to the other handlers.
    assert await platform_event(client, "acct_nobody", "invoice.paid", invoice("cus_x", "x@buyer.example")) == "ignored"


async def test_disconnect_and_deauthorize(client, db, prog, oauth):
    h = auth(prog["token"])
    assert (await client.delete("/merchant/stripe", headers=h)).json() == {"ok": True}
    assert oauth.deauthorized == ["acct_one"]
    await client.post("/merchant/stripe/oauth", json={"code": "two", "state": await start(client, prog)}, headers=h)
    assert await platform_event(client, "acct_two", "account.application.deauthorized", {"id": "ca_test", "object": "application"}) == "merchant disconnected"
    assert (await client.get("/merchant", headers=h)).json()["stripe"] is None
