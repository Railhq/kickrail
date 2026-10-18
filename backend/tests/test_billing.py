"""Kickrail's own plans: trial, gates, checkout, subscription sync and the revenue meter."""

import json
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from app import deps, plans
from app.main import app
from app.services import billing

from .conftest import sign


def auth(token):
    return {"authorization": f"Bearer {token}"}


class FakeBilling:
    def __init__(self):
        self.checkouts: list[dict] = []
        self.changes: list[tuple[str, str]] = []

    async def price_id(self, plan, interval):
        return f"price_{plan}_{interval}"

    async def checkout(self, **kw):
        self.checkouts.append(kw)
        return "https://checkout.stripe.test/sub"

    async def change_price(self, subscription_id, price):
        self.changes.append((subscription_id, price))
        _, plan, interval = price.split("_")
        return sub_obj(self.merchant_id, plan, interval, sub_id=subscription_id)

    async def portal(self, customer, return_url):
        return f"https://billing.stripe.test/{customer}"


def sub_obj(mid, plan, interval="month", status="active", sub_id="sub_1", **extra):
    return {
        "id": sub_id, "object": "subscription", "customer": "cus_kr1", "status": status, "metadata": {"kr_merchant": mid},
        "cancel_at_period_end": False, "trial_end": None,
        "items": {"data": [{"id": "si_1", "current_period_end": int((datetime.now(UTC) + timedelta(days=30)).timestamp()), "price": {"id": f"price_{plan}_{interval}", "lookup_key": f"kickrail_{plan}_{interval}", "metadata": {"kr_plan": plan}, "recurring": {"interval": interval}}}]},
    } | extra


async def platform_event(client, type_, obj, created=None):
    event = {"id": f"evt_{secrets.token_hex(6)}", "type": type_, "created": created or int(datetime.now(UTC).timestamp()), "data": {"object": obj}}
    payload = json.dumps(event)
    return await client.post("/webhooks/platform", content=payload, headers={"stripe-signature": sign(payload, "whsec_platform"), "content-type": "application/json"})


@pytest.fixture(scope="module")
def fake_billing():
    fb = FakeBilling()
    app.dependency_overrides[deps.billing_api] = lambda: fb
    yield fb
    app.dependency_overrides.pop(deps.billing_api, None)


@pytest.fixture(scope="module")
async def prog(client, db):
    r = await client.post("/auth/signup", json={"email": "owner@billing.example", "password": "correct-horse", "name": "Bea"})
    token = r.json()["token"]
    await db.users.update_one({"email": "owner@billing.example"}, {"$set": {"email_verified": True}})
    r = await client.post("/merchant", json={"name": "Billco", "website": "https://billco.example"}, headers=auth(token))
    return {"token": token, "id": r.json()["merchant"]["id"], "sk": r.json()["secret_key"]}


async def test_new_program_starts_a_growth_trial(client, prog):
    b = (await client.get("/merchant/billing", headers=auth(prog["token"]))).json()
    assert b["plan"]["id"] == "growth" and b["plan"]["status"] == "trialing" and b["can_manage"]
    left = datetime.fromisoformat(b["plan"]["trial_ends_at"]) - datetime.now(UTC)
    assert timedelta(days=13) < left <= timedelta(days=14)
    assert [p["id"] for p in b["plans"]] == ["free", "starter", "growth", "scale"]
    assert b["usage"]["cap_cents"] == 5_000_000 and not b["usage"]["over_limit"]


async def test_free_plan_gates_but_never_stops_tracking(client, db, prog):
    await db.merchants.update_one({"_id": prog["id"]}, {"$set": {"plan.trial_ends_at": datetime.now(UTC) - timedelta(minutes=1)}})
    h = auth(prog["token"])
    m = (await client.get("/merchant", headers=h)).json()
    assert m["plan"]["id"] == "free" and m["plan"]["status"] == "trial_ended"
    camp = {"name": "Second", "rule_type": "percent", "percent": 20, "duration_mode": "forever", "hold_days": 0, "min_payout_cents": 0}
    r = await client.post("/merchant/campaigns", json=camp, headers=h)
    assert r.status_code == 402 and "Starter" in r.json()["detail"]
    assert (await client.post("/merchant/domains", json={"host": "partners.billco.example"}, headers=h)).status_code == 402
    assert (await client.post("/merchant/team/invites", json={"email": "mate@billco.example"}, headers=h)).status_code == 402
    assert (await client.post("/merchant/webhooks", json={"url": "https://billco.example/hook"}, headers=h)).status_code == 402
    assert (await client.post("/merchant/payouts", json={"currency": "usd", "method": "stripe"}, headers=h)).status_code == 402
    # Reporting signups over the API always works; managing affiliates over it is Growth and up.
    assert (await client.post("/v1/referrals", json={"email": "buyer@billco.example"}, headers=auth(prog["sk"]))).status_code == 200
    r = await client.get("/v1/affiliates", headers=auth(prog["sk"]))
    assert r.status_code == 402 and "Growth" in r.json()["detail"]
    assert (await client.get("/programs/billco")).json()["powered_by"] is True


async def test_checkout_and_subscription_sync(client, db, prog, fake_billing):
    h = auth(prog["token"])
    fake_billing.merchant_id = prog["id"]
    r = await client.post("/merchant/billing/checkout", json={"plan": "starter", "interval": "year"}, headers=h)
    assert r.json() == {"url": "https://checkout.stripe.test/sub"}
    c = fake_billing.checkouts[-1]
    assert c["price"] == "price_starter_year" and c["merchant_id"] == prog["id"] and c["trial_end"] is None and c["email"] == "owner@billing.example"
    assert (await platform_event(client, "checkout.session.completed", {"id": "cs_1", "mode": "subscription", "customer": "cus_kr1", "subscription": "sub_1", "metadata": {"kr_merchant": prog["id"]}})).json()["outcome"] == "checkout recorded"
    r = await platform_event(client, "customer.subscription.created", sub_obj(prog["id"], "starter", "year"))
    assert r.json()["outcome"] == "starter active"
    m = (await client.get("/merchant", headers=h)).json()
    assert m["plan"]["id"] == "starter" and m["plan"]["interval"] == "year" and m["plan"]["subscribed"] and m["plan"]["limits"]["domains"] == 1
    # Now a second campaign is allowed; webhooks still need Growth.
    camp = {"name": "Second", "rule_type": "percent", "percent": 20, "duration_mode": "forever", "hold_days": 0, "min_payout_cents": 0}
    assert (await client.post("/merchant/campaigns", json=camp, headers=h)).status_code == 200
    # Changing plan updates the subscription in place.
    assert (await client.post("/merchant/billing/checkout", json={"plan": "growth", "interval": "month"}, headers=h)).json() == {"changed": True}
    assert fake_billing.changes[-1] == ("sub_1", "price_growth_month")
    assert (await client.get("/merchant", headers=h)).json()["plan"]["id"] == "growth"
    assert (await client.get("/programs/billco")).json()["powered_by"] is False
    # An event older than what we have is ignored.
    old = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
    assert (await platform_event(client, "customer.subscription.updated", sub_obj(prog["id"], "starter"), created=old)).json()["outcome"] == "stale event"
    assert (await client.post("/merchant/billing/portal", headers=h)).json()["url"] == "https://billing.stripe.test/cus_kr1"
    # Payment trouble keeps the plan while Stripe retries; cancelling drops to Free.
    await platform_event(client, "customer.subscription.updated", sub_obj(prog["id"], "growth", status="past_due"))
    p = (await client.get("/merchant", headers=h)).json()["plan"]
    assert p["id"] == "growth" and p["status"] == "past_due"
    await platform_event(client, "customer.subscription.deleted", sub_obj(prog["id"], "growth", status="canceled"))
    m = (await client.get("/merchant", headers=h)).json()
    assert m["plan"]["id"] == "free" and not m["plan"]["subscribed"]
    # Extra campaigns made on Starter keep running.
    assert len((await client.get("/merchant/campaigns", headers=h)).json()) == 2


async def test_checkout_during_trial_charges_when_it_ends(client, db, fake_billing):
    r = await client.post("/auth/signup", json={"email": "trial@billing.example", "password": "correct-horse", "name": "Tia"})
    token = r.json()["token"]
    await db.users.update_one({"email": "trial@billing.example"}, {"$set": {"email_verified": True}})
    await client.post("/merchant", json={"name": "Trialco", "website": "https://trialco.example"}, headers=auth(token))
    await client.post("/merchant/billing/checkout", json={"plan": "scale", "interval": "month"}, headers=auth(token))
    c = fake_billing.checkouts[-1]
    assert c["price"] == "price_scale_month" and c["trial_end"] and c["trial_end"] > datetime.now(UTC).timestamp() + 13 * 86400


async def test_only_the_owner_manages_billing(client, db, prog, fake_billing):
    await db.merchants.update_one({"_id": prog["id"]}, {"$push": {"member_ids": "usr_someone"}})
    await db.users.insert_one({"_id": "usr_someone", "email": "mate@billing.example", "name": "Mate", "email_verified": True, "password_hash": "x"})
    from app.security import issue_token

    r = await client.post("/merchant/billing/checkout", json={"plan": "starter"}, headers=auth(issue_token({"_id": "usr_someone"})))
    assert r.status_code == 403


async def test_billing_off_without_a_platform_key(client, prog):
    app.dependency_overrides.pop(deps.billing_api, None)
    r = await client.post("/merchant/billing/checkout", json={"plan": "starter"}, headers=auth(prog["token"]))
    assert r.status_code == 503 and "billing" in r.json()["detail"]
    assert (await client.get("/merchant/billing", headers=auth(prog["token"]))).json()["enabled"] is False


async def test_revenue_meter_and_over_limit_notice(client, db, prog):
    now = datetime.now(UTC)
    last, before = billing.months_back(now, 1) + timedelta(days=3), billing.months_back(now, 2) + timedelta(days=3)
    # Free covers $1,000 a month. CAD 1,500 is about USD 1,080.
    for i, (when, cents, cur) in enumerate([(last, 150_000, "cad"), (before, 90_000, "usd"), (before, 20_000, "usd"), (now, 5_000, "usd")]):
        await db.commissions.insert_one({"_id": f"com_meter{i}", "merchant_id": prog["id"], "source_key": f"meter{i}", "status": "pending", "base_cents": cents, "amount_cents": cents // 10, "currency": cur, "created_at": when})
    u = await billing.usage(db, await db.merchants.find_one({"_id": prog["id"]}), now)
    assert u["over_limit"] and u["suggested_plan"] == "starter" and u["this_month_cents"] == 5_000
    assert u["months"][1]["revenue_cents"] == billing.to_usd_cents(150_000, "cad")
    await db.merchants.update_one({"_id": prog["id"]}, {"$unset": {"usage": ""}})
    await billing.check_limits(db, now)
    await billing.check_limits(db, now)
    mails = await db.emails.find({"kind": "plan_over_limit", "to": "owner@billing.example"}).to_list(None)
    assert len(mails) == 1 and "Starter plan ($29/month) covers up to $10,000" in mails[0]["text"]
    m = (await client.get("/merchant", headers=auth(prog["token"]))).json()
    assert m["plan"]["over_limit"] and m["plan"]["suggested_plan"] == "starter"


async def test_comped_programs_get_scale_free(client, db, prog):
    await db.merchants.update_one({"_id": prog["id"]}, {"$set": {"comped": True}})
    m = (await client.get("/merchant", headers=auth(prog["token"]))).json()
    assert m["plan"]["id"] == "scale" and m["plan"]["comped"] and not m["plan"]["over_limit"] and m["domain_limit"] == 10
    assert plans.current(await db.merchants.find_one({"_id": prog["id"]}))["revenue_cap"] is None
    assert (await client.get("/v1/affiliates", headers=auth(prog["sk"]))).status_code == 200
