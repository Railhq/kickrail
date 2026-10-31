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


async def platform_event(client, type_, obj, created=None, path="/webhooks/billing", secret="whsec_billing"):
    """Billing events, by default as the billing account sends them."""
    event = {"id": f"evt_{secrets.token_hex(6)}", "type": type_, "created": created or int(datetime.now(UTC).timestamp()), "data": {"object": obj}}
    payload = json.dumps(event)
    return await client.post(path, content=payload, headers={"stripe-signature": sign(payload, secret), "content-type": "application/json"})


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
    # A higher plan can opt back in, and out again.
    await client.put("/merchant/branding", json={"show_powered_by": True}, headers=h)
    assert (await client.get("/programs/billco")).json()["powered_by"] is True
    await client.put("/merchant/branding", json={"show_powered_by": False}, headers=h)
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


# ---------- a billing account shared with other products ----------


async def new_program(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": "Sam"})
    token = r.json()["token"]
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    r = await client.post("/merchant", json={"name": name, "website": f"https://{name.lower()}.example"}, headers=auth(token))
    return {"token": token, "id": r.json()["merchant"]["id"]}


def foreign_sub(sub_id="sub_pass1", **meta):
    return {
        "id": sub_id, "object": "subscription", "customer": "cus_other", "status": "active", "metadata": meta, "cancel_at_period_end": False,
        "items": {"data": [{"id": "si_x", "price": {"id": "price_pass", "lookup_key": "railhq_pass_month", "recurring": {"interval": "month"}}}]},
    }


async def test_foreign_subscription_events_are_ignored(client, db):
    p = await new_program(client, db, "own@shared.example", "Sharedco")
    before = await db.merchants.find_one({"_id": p["id"]})
    events = await db.stripe_events.count_documents({})
    for kind in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        # Another product's subscription, untagged or tagged for itself; even one that names a program.
        for obj in (foreign_sub(), foreign_sub(product="railhq_pass", railhq_user="usr_1"), foreign_sub(product="pathrail", kr_merchant=p["id"])):
            r = await platform_event(client, kind, obj)
            assert r.status_code == 200 and r.json() == {"outcome": "ignored"}
    # Odd payloads are still a 200.
    for obj in ({}, {"metadata": None}, {"id": 5, "metadata": {"kr_merchant": 7}}):
        assert (await platform_event(client, "customer.subscription.updated", obj)).status_code == 200
    assert (await platform_event(client, "invoice.paid", {"id": "in_x", "customer": "cus_other"})).json() == {"outcome": "ignored"}
    after = await db.merchants.find_one({"_id": p["id"]})
    assert after["plan"] == before["plan"]
    assert await db.stripe_events.count_documents({}) == events


async def test_foreign_checkout_is_ignored_and_ours_is_processed(client, db):
    p = await new_program(client, db, "own2@shared.example", "Sharedtwo")
    for obj in (
        {"id": "cs_pass", "mode": "subscription", "customer": "cus_other", "metadata": {"product": "railhq_pass", "railhq_user": "usr_1"}},
        {"id": "cs_nometa", "mode": "subscription", "customer": "cus_other"},
        {"id": "cs_other", "mode": "subscription", "customer": "cus_other", "metadata": {"product": "demorail", "kr_merchant": p["id"]}},
        {"id": "cs_gone", "mode": "subscription", "customer": "cus_other", "metadata": {"product": "kickrail", "kr_merchant": "mer_nope"}},
        {"id": "cs_pay", "mode": "payment", "customer": "cus_other", "metadata": {"kr_merchant": p["id"]}},
    ):
        r = await platform_event(client, "checkout.session.completed", obj)
        assert r.status_code == 200 and r.json() == {"outcome": "ignored"}
    assert not (await db.merchants.find_one({"_id": p["id"]}))["plan"].get("stripe_customer")
    assert not await db.merchants.find_one({"_id": "mer_nope"})

    meta = {"kr_merchant": p["id"], "product": "kickrail"}
    r = await platform_event(client, "checkout.session.completed", {"id": "cs_ours", "mode": "subscription", "customer": "cus_ours", "metadata": meta})
    assert r.json()["outcome"] == "checkout recorded"
    r = await platform_event(client, "customer.subscription.created", sub_obj(p["id"], "growth", sub_id="sub_ours", customer="cus_ours", metadata=meta))
    assert r.json()["outcome"] == "growth active"
    # Later events found by the subscription id alone are ours too.
    r = await platform_event(client, "customer.subscription.updated", sub_obj(p["id"], "growth", status="past_due", sub_id="sub_ours", customer="cus_ours", metadata={}))
    assert r.json()["outcome"] == "growth past_due"
    plan = (await db.merchants.find_one({"_id": p["id"]}))["plan"]
    assert plan["stripe_customer"] == "cus_ours" and plan["stripe_subscription"] == "sub_ours" and plan["status"] == "past_due"
    ev = await db.stripe_events.find_one({"type": "customer.subscription.created", "merchant_id": p["id"]})
    assert ev["endpoint"] == "billing" and ev["status"] == "done"


async def test_billing_and_connect_events_never_cross(client, db):
    await db.partners.insert_one({"_id": "prt_cross", "connect_account_id": "acct_cross", "payouts_enabled": False})
    connect_obj = {"id": "acct_cross", "payouts_enabled": True, "capabilities": {"transfers": "active"}}
    payout_obj = {"id": "cs_payout", "mode": "payment", "metadata": {"kr_payout": "pay_cross"}}
    # Signed by the billing account: Connect and payout handling never see it, on either endpoint.
    for path in ("/webhooks/billing", "/webhooks/platform"):
        assert (await platform_event(client, "account.updated", connect_obj, path=path)).json() == {"outcome": "ignored"}
        assert (await platform_event(client, "checkout.session.completed", payout_obj, path=path)).json() == {"outcome": "ignored"}
    assert (await db.partners.find_one({"_id": "prt_cross"}))["payouts_enabled"] is False
    # The billing endpoint refuses the platform's signature.
    assert (await platform_event(client, "account.updated", connect_obj, secret="whsec_platform")).status_code == 400
    # The platform's own events still reach Connect handling.
    r = await platform_event(client, "account.updated", connect_obj, path="/webhooks/platform", secret="whsec_platform")
    assert r.json()["outcome"] == "payouts_enabled=True"
    assert (await db.partners.find_one({"_id": "prt_cross"}))["payouts_enabled"] is True


async def test_billing_events_sent_to_the_old_endpoint_still_bill(client, db):
    p = await new_program(client, db, "own3@shared.example", "Sharedthree")
    r = await platform_event(client, "customer.subscription.created", sub_obj(p["id"], "scale", sub_id="sub_old_ep"), path="/webhooks/platform")
    assert r.json()["outcome"] == "scale active"
    assert (await db.stripe_events.find_one({"type": "customer.subscription.created", "merchant_id": p["id"]}))["endpoint"] == "billing"
    assert (await platform_event(client, "customer.subscription.updated", foreign_sub(), path="/webhooks/platform")).json() == {"outcome": "ignored"}


# ---------- the Stripe calls themselves ----------


class _Obj(dict):
    __getattr__ = dict.get


class FakeStripeClient:
    def __init__(self, prices=None, missing_customers=()):
        self.prices = prices or {}
        self.missing_customers = set(missing_customers)
        self.sessions: list[dict] = []
        self.portal_sessions: list[dict] = []
        self.created: list[str] = []
        c = self

        class Prices:
            async def list_async(self, params):
                p = c.prices.get(params["lookup_keys"][0])
                return _Obj(data=[p] if p else [])

            async def create_async(self, params):
                c.created.append("price")

        class Products:
            async def create_async(self, params):
                c.created.append("product")

        class Sessions:
            async def create_async(self, params):
                import stripe

                if params.get("customer") in c.missing_customers:
                    raise stripe.InvalidRequestError("No such customer", "customer", code="resource_missing")
                c.sessions.append(params)
                return _Obj(url="https://checkout.stripe.test/cs")

        class PortalSessions:
            async def create_async(self, params):
                c.portal_sessions.append(params)
                return _Obj(url="https://billing.stripe.test/p")

        class PortalConfigs:
            async def list_async(self, params):
                return _Obj(data=[_Obj(id="bpc_tagged", metadata={"kr": "billing"})])

        self.v1 = _Obj(prices=Prices(), products=Products(), checkout=_Obj(sessions=Sessions()),
                       billing_portal=_Obj(sessions=PortalSessions(), configurations=PortalConfigs()))


def stripe_billing(fake):
    b = billing.Billing.__new__(billing.Billing)
    b.c = fake
    b._prices = {}
    return b


def price(pid, interval, amount, currency="usd"):
    return _Obj(id=pid, recurring={"interval": interval}, unit_amount=amount, currency=currency)


async def test_prices_are_looked_up_never_created():
    fake = FakeStripeClient({"kickrail_growth_year": price("price_gy", "year", 79_000)})
    b = stripe_billing(fake)
    assert await b.price_id("growth", "year") == "price_gy"
    with pytest.raises(billing.BillingSetupError, match="kickrail_scale_month"):
        await b.price_id("scale", "month")
    fake.prices["kickrail_starter_month"] = price("price_sy", "year", 29_000)
    with pytest.raises(billing.BillingSetupError, match="per month"):
        await b.price_id("starter", "month")
    assert fake.created == []


async def test_missing_price_is_a_clear_503(client, db):
    p = await new_program(client, db, "own4@shared.example", "Sharedfour")
    app.dependency_overrides[deps.billing_api] = lambda: stripe_billing(FakeStripeClient())
    try:
        r = await client.post("/merchant/billing/checkout", json={"plan": "starter", "interval": "month"}, headers=auth(p["token"]))
    finally:
        app.dependency_overrides.pop(deps.billing_api, None)
    assert r.status_code == 503 and "kickrail_starter_month" in r.json()["detail"]


async def checkout_params(monkeypatch, managed: bool, customer=None, missing=()):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "stripe_managed_payments", managed)
    fake = FakeStripeClient(missing_customers=missing)
    url = await stripe_billing(fake).checkout(merchant_id="mer_1", customer=customer, email="o@x.example", price="price_1", trial_end=1_900_000_000,
                                              success_url="https://kickrail.test/ok", cancel_url="https://kickrail.test/no")
    assert url == "https://checkout.stripe.test/cs"
    return fake.sessions


async def test_checkout_session_params(monkeypatch):
    (s,) = await checkout_params(monkeypatch, managed=False)
    assert "managed_payments" not in s
    assert s["metadata"] == {"kr_merchant": "mer_1", "product": "kickrail"}
    assert s["subscription_data"] == {"metadata": {"kr_merchant": "mer_1", "product": "kickrail"}, "trial_end": 1_900_000_000}
    assert s["branding_settings"] == {"display_name": "Kickrail", "logo": {"type": "url", "url": "https://kickrail.test/icon-512.png"}}
    assert s["customer_email"] == "o@x.example" and "customer" not in s

    (s,) = await checkout_params(monkeypatch, managed=True, customer="cus_1")
    assert s["managed_payments"] == {"enabled": True}
    assert s["customer"] == "cus_1" and "customer_email" not in s
    assert s["subscription_data"]["metadata"]["product"] == "kickrail" and s["branding_settings"]["display_name"] == "Kickrail"
    assert not set(s) & set(billing.MP_UNSUPPORTED)


async def test_checkout_with_a_customer_from_the_old_account_starts_fresh(monkeypatch):
    (s,) = await checkout_params(monkeypatch, managed=True, customer="cus_old", missing={"cus_old"})
    assert "customer" not in s and s["customer_email"] == "o@x.example"


def test_managed_payments_strips_what_it_does_not_allow():
    out = billing.managed_payments_params({
        "mode": "subscription", "automatic_tax": {"enabled": True}, "tax_id_collection": {"enabled": True}, "payment_method_types": ["card"],
        "customer_update": {"name": "auto", "address": "auto"}, "allow_promotion_codes": True,
        "subscription_data": {"metadata": {"product": "kickrail"}, "default_tax_rates": ["txr_1"], "invoice_settings": {}, "trial_end": 5},
    })
    assert out == {"mode": "subscription", "allow_promotion_codes": True, "managed_payments": {"enabled": True},
                   "subscription_data": {"metadata": {"product": "kickrail"}, "trial_end": 5}}


async def test_portal_uses_the_configured_configuration(monkeypatch):
    from app.config import get_settings

    fake = FakeStripeClient()
    b = stripe_billing(fake)
    assert await b.portal("cus_1", "https://kickrail.test/back") == "https://billing.stripe.test/p"
    assert fake.portal_sessions[-1]["configuration"] == "bpc_tagged"
    monkeypatch.setattr(get_settings(), "stripe_portal_configuration", "bpc_railhq_kickrail")
    await b.portal("cus_1", "https://kickrail.test/back")
    assert fake.portal_sessions[-1] == {"customer": "cus_1", "return_url": "https://kickrail.test/back", "configuration": "bpc_railhq_kickrail"}


def test_managed_payments_needs_its_own_billing_key(monkeypatch):
    from app.config import Settings

    s = Settings(platform_stripe_secret_key="sk_platform", billing_stripe_secret_key="")
    assert s.billing_key == "sk_platform"
    s = Settings(platform_stripe_secret_key="sk_platform", billing_stripe_secret_key="", stripe_managed_payments=True)
    assert s.billing_key == ""
    s = Settings(platform_stripe_secret_key="sk_platform", billing_stripe_secret_key="rk_billing", stripe_managed_payments=True)
    assert s.billing_key == "rk_billing" and s.oauth_key == "sk_platform"
