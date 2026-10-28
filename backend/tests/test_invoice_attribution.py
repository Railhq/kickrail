"""Subscriptions bought through Stripe Checkout: a code typed at checkout and the order
Stripe sends the events in must not change who earns."""

import time

import pytest

from app.db import get_db

from .conftest import send_event

S = {}
pytestmark = pytest.mark.asyncio(loop_scope="session")


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, email, name, partner=False):
    # Affiliates sign up on the portal: their own login, separate from the dashboard's.
    r = await client.post("/partner/auth/signup" if partner else "/auth/signup", json={"email": email, "password": "correct-horse", "name": name}, headers={"x-forwarded-for": f"10.0.9.{len(S) + 1}"})
    await (await get_db())["partners" if partner else "users"].update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


def hook(client, type_, obj):
    return send_event(client, f"/webhooks/stripe/{S['merchant_id']}", "whsec_merchant", type_, obj)


def invoice(inv_id, customer, discounts=None):
    return {"id": inv_id, "customer": customer, "amount_paid": 1615, "currency": "usd", "status_transitions": {"paid_at": int(time.time())}, "discounts": discounts or []}


async def test_setup(client):
    S["owner"] = await signup(client, "owner@subco.example", "Sub Owner")
    r = await client.post("/merchant", json={"name": "Subco", "website": "https://subco.example"}, headers=auth(S["owner"]))
    S["merchant_id"], S["pk"] = r.json()["merchant"]["id"], r.json()["merchant"]["public_key"]
    await client.post("/merchant/stripe", json={"restricted_key": "rk_test_subco"}, headers=auth(S["owner"]))
    camp = (await client.get("/merchant/campaigns", headers=auth(S["owner"]))).json()[0]
    await client.put(f"/merchant/campaigns/{camp['id']}", json={"name": "Default", "rule_type": "percent", "percent": 30, "duration_mode": "forever", "hold_days": 30, "min_payout_cents": 0, "stripe_coupon_id": "coupon_20"}, headers=auth(S["owner"]))
    a = (await client.post("/programs/subco/join", json={}, headers=auth(await signup(client, "kim@creators.example", "Kim Creator", partner=True)))).json()
    S["aff_id"], S["token"], S["code"] = a["id"], a["token"], a["code"]


async def test_code_on_an_invoice_is_found_through_its_discount_id(client, db, fakes):
    fakes["merchant"].invoices["in_code"] = {"id": "in_code", "discounts": [{"id": "di_1", "promotion_code": f"promo_{S['code']}"}]}
    r = await hook(client, "invoice.paid", invoice("in_code", "cus_code", ["di_1"]))
    assert r.json()["outcome"] == "commission 484 usd"
    assert (await db.referrals.find_one({"stripe_customer_id": "cus_code"}))["affiliate_id"] == S["aff_id"]


async def test_checkout_earns_the_first_invoice_when_invoice_paid_came_first(client, db, fakes):
    await client.post("/track/click", content=f'{{"key":"{S["pk"]}","id":"kr_subcoclick000000001","token":"{S["token"]}"}}')
    inv = invoice("in_first", "cus_first")
    fakes["merchant"].invoices["in_first"] = inv
    assert (await hook(client, "invoice.paid", inv)).json()["outcome"] == "no referral"
    session = {"id": "cs_sub", "mode": "subscription", "payment_status": "paid", "customer": "cus_first", "invoice": "in_first",
               "customer_details": {"email": "first@buyer.example"}, "metadata": {"kr_ref": "kr_subcoclick000000001"}}
    assert (await hook(client, "checkout.session.completed", session)).json()["outcome"] == "commission 484 usd"
    # Stripe retrying invoice.paid later doesn't pay twice.
    assert (await hook(client, "invoice.paid", inv)).json()["outcome"] == "already earned"
    assert await db.commissions.count_documents({"source_key": "inv:in_first"}) == 1
