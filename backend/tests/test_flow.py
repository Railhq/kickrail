"""End to end through the HTTP API: merchant setup, affiliate join, click, server-side
signup, Stripe webhooks, refunds, fraud holds, manual and Stripe payouts."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.db import get_db

from .conftest import send_event

S = {}  # state shared across the ordered tests in this module
pytestmark = pytest.mark.asyncio(loop_scope="session")


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name}, headers={"x-forwarded-for": f"10.0.0.{len(S) + 1}"})
    assert r.status_code == 200, r.text
    await (await get_db()).users.update_one({"email": email}, {"$set": {"email_verified": True}})  # as if they clicked the link
    return r.json()["token"]


def hook_url():
    return f"/webhooks/stripe/{S['merchant_id']}"


async def test_requires_internal_token(client):
    r = await client.get("/auth/me", headers={"x-internal-token": "nope"})
    assert r.status_code == 403


async def test_merchant_setup(client, fakes):
    S["owner"] = await signup(client, "founder@acme.io", "Founder")
    r = await client.post("/merchant", json={"name": "Acme", "website": "https://acme.io"}, headers=auth(S["owner"]))
    assert r.status_code == 200, r.text
    body = r.json()
    S["merchant_id"], S["pk"], S["sk"] = body["merchant"]["id"], body["merchant"]["public_key"], body["secret_key"]
    assert "kr.js?k=pk_kr_" in body["merchant"]["snippet"]

    r = await client.post("/merchant/stripe", json={"restricted_key": "rk_test_abc123"}, headers=auth(S["owner"]))
    assert r.status_code == 200, r.text
    assert r.json()["stripe"]["account_name"] == "Acme"
    assert fakes["merchant"].webhook_url == f"https://kickrail.test/api/webhooks/stripe/{S['merchant_id']}"

    camps = (await client.get("/merchant/campaigns", headers=auth(S["owner"]))).json()
    S["campaign_id"] = camps[0]["id"]
    # 30% for 12 months, 30-day hold, $20 min, with a coupon so creator codes are redeemable
    r = await client.put(
        f"/merchant/campaigns/{S['campaign_id']}",
        json={"name": "Default", "rule_type": "percent", "percent": 30, "duration_mode": "months", "months": 12, "hold_days": 30, "min_payout_cents": 2000, "stripe_coupon_id": "coupon_20"},
        headers=auth(S["owner"]),
    )
    assert r.json()["description"] == "30% of every payment for 12 months"


async def test_affiliate_joins_with_one_account(client, fakes):
    S["aff"] = await signup(client, "creator@youtube.example", "Jane Creator")
    prog = (await client.get("/programs/acme")).json()
    assert prog["terms"] == "30% of every payment for 12 months"
    r = await client.post("/programs/acme/join", json={}, headers=auth(S["aff"]))
    assert r.status_code == 200, r.text
    a = r.json()
    S["aff_id"], S["token"] = a["id"], a["token"]
    assert a["status"] == "approved" and a["token"] == "janecreator" and a["code"] == "JANECREATOR"
    assert ("coupon_20", "JANECREATOR") in fakes["merchant"].promotion_codes
    again = (await client.post("/programs/acme/join", json={}, headers=auth(S["aff"]))).json()
    assert again["id"] == S["aff_id"]


async def test_script_and_test_link(client):
    r = await client.get(f"/kr.js?k={S['pk']}")
    assert r.status_code == 200 and '"params": ["via", "ref"]' in r.text and "__KR_CONFIG__" not in r.text
    r = await client.post("/track/click", content=f'{{"key":"{S["pk"]}","id":"kr_testclick0000000001","token":"{S["token"]}","url":"https://acme.io/?via=x&kr_test=1","test":true}}')
    assert r.status_code == 204
    d = (await client.get(f"/portal/{S['aff_id']}", headers=auth(S["aff"]))).json()
    assert d["last_test"]["url"].startswith("https://acme.io/") and d["clicks"] == 0


async def test_click_signup_checkout_invoice(client, db, fakes):
    S["click"] = "kr_AbCdEfGhIjKlMnOpQrSt"
    r = await client.post("/track/click", content=f'{{"key":"{S["pk"]}","id":"{S["click"]}","token":"{S["token"].upper()}","url":"https://acme.io/?via={S["token"]}"}}')
    assert r.status_code == 204
    # Merchant backend reports the signup, server to server
    r = await client.post("/v1/referrals", json={"referral": S["click"], "email": "buyer@bigco.com", "user_id": "u_42", "ip": "203.0.113.9"}, headers=auth(S["sk"]))
    assert r.json()["referred"] and r.json()["created"]
    S["ref_id"] = r.json()["referral"]["id"]

    # Subscription checkout: links the Stripe customer, earns nothing by itself
    r = await send_event(client, hook_url(), "whsec_merchant", "checkout.session.completed",
                         {"id": "cs_1", "mode": "subscription", "payment_status": "paid", "client_reference_id": S["click"], "customer": "cus_1", "customer_details": {"email": "buyer@bigco.com"}, "currency": "usd", "amount_total": 11000})
    assert r.json()["outcome"] == "referral linked"

    fakes["merchant"].invoice_pi["in_1"] = "pi_1"
    paid = int(time.time())
    invoice = {"id": "in_1", "customer": "cus_1", "customer_email": "buyer@bigco.com", "amount_paid": 11000, "total_taxes": [{"amount": 1000}], "currency": "usd", "status_transitions": {"paid_at": paid}, "created": paid}
    r = await send_event(client, hook_url(), "whsec_merchant", "invoice.paid", invoice, event_id="evt_inv1")
    assert r.json()["outcome"] == "commission 3000 usd"  # 30% of 100.00 (tax excluded)
    assert (await send_event(client, hook_url(), "whsec_merchant", "invoice.paid", invoice, event_id="evt_inv1")).json()["outcome"] == "duplicate"
    assert (await send_event(client, hook_url(), "whsec_merchant", "invoice.paid", invoice)).json()["outcome"] == "already earned"
    ref = await db.referrals.find_one({"_id": S["ref_id"]})
    assert ref["status"] == "customer" and ref["stripe_customer_id"] == "cus_1" and ref["external_user_id"] == "u_42"


async def test_bad_signature_rejected(client):
    r = await client.post(hook_url(), content='{"id":"evt_x","type":"invoice.paid","data":{"object":{}}}', headers={"stripe-signature": "t=1,v1=deadbeef"})
    assert r.status_code == 400


async def test_partial_refund_shrinks_unpaid_commission(client, db):
    r = await send_event(client, hook_url(), "whsec_merchant", "charge.refunded", {"id": "ch_1", "payment_intent": "pi_1", "amount": 11000, "amount_refunded": 2750})
    assert r.json()["outcome"] == "reduced to 2250"
    c = await db.commissions.find_one({"source_key": "inv:in_1"})
    assert c["amount_cents"] == 2250 and c["refunded_cents"] == 2750


async def test_first_referral_wins(client, db):
    other = await signup(client, "rival@example.org", "Rival")
    rival = (await client.post("/programs/acme/join", json={}, headers=auth(other))).json()
    await client.post("/track/click", content=f'{{"key":"{S["pk"]}","id":"kr_rivalclick000000001","token":"{rival["token"]}"}}')
    r = await client.post("/v1/referrals", json={"referral": "kr_rivalclick000000001", "email": "buyer@bigco.com"}, headers=auth(S["sk"]))
    assert r.json()["referral"]["affiliate_id"] == S["aff_id"] and not r.json()["created"]


async def test_creator_code_at_checkout_without_any_click(client, db):
    r = await send_event(client, hook_url(), "whsec_merchant", "checkout.session.completed",
                         {"id": "cs_2", "mode": "payment", "payment_status": "paid", "customer": None, "customer_details": {"email": "podcast-listener@example.net"}, "currency": "usd", "amount_total": 5000, "total_details": {"amount_tax": 0}, "payment_intent": "pi_2", "discounts": [{"promotion_code": "promo_JANECREATOR"}]})
    assert r.json()["outcome"] == "commission 1500 usd"
    ref = await db.referrals.find_one({"email": "podcast-listener@example.net"})
    assert ref["source"] == "code" and ref["affiliate_id"] == S["aff_id"]


async def test_self_referral_is_held_for_review(client, db):
    r = await client.post("/v1/referrals", json={"via": S["token"], "email": "Creator+alt@YouTube.example", "stripe_customer_id": "cus_self"}, headers=auth(S["sk"]))
    assert r.json()["referral"]["flagged"]
    S["self_ref"] = r.json()["referral"]["id"]
    paid = int(time.time())
    r = await send_event(client, hook_url(), "whsec_merchant", "invoice.paid", {"id": "in_self", "customer": "cus_self", "amount_paid": 10000, "currency": "usd", "status_transitions": {"paid_at": paid}})
    assert r.json()["outcome"] == "commission 3000 usd"
    assert (await db.commissions.find_one({"source_key": "inv:in_self"}))["held"] is True
    flagged = (await client.get("/merchant/referrals?flagged=true", headers=auth(S["owner"]))).json()
    assert [f["id"] for f in flagged] == [S["self_ref"]]


async def age_commissions(db):
    """Skip the 30-day hold."""
    await db.commissions.update_many({"merchant_id": S["merchant_id"]}, {"$set": {"due_at": datetime.now(UTC) - timedelta(days=1)}})


async def test_manual_payout_excludes_held(client, db):
    await age_commissions(db)
    p = (await client.get("/merchant/payouts", headers=auth(S["owner"]))).json()
    assert [(l["affiliate_id"], l["amount_cents"]) for l in p["payable"]] == [(S["aff_id"], 2250 + 1500)]
    # The affiliate saves where to be paid; the merchant sees it in the due list and CSV
    r = await client.put("/payout-account/details", json={"method": "paypal", "value": "jane.pp@example.com"}, headers=auth(S["aff"]))
    assert r.status_code == 200, r.text
    assert (await client.get("/payout-account", headers=auth(S["aff"]))).json()["details"]["value"] == "jane.pp@example.com"
    p = (await client.get("/merchant/payouts", headers=auth(S["owner"]))).json()
    assert p["payable"][0]["payout_details"]["method"] == "paypal"
    due = (await client.get("/merchant/payouts/due.csv?currency=usd", headers=auth(S["owner"]))).text
    assert "Jane Creator,creator@youtube.example,paypal,jane.pp@example.com,37.50,USD,2" in due

    # Selecting nobody payable is an error, not a silent pay-everyone
    r = await client.post("/merchant/payouts", json={"currency": "usd", "method": "manual", "affiliate_ids": ["aff_nobody"]}, headers=auth(S["owner"]))
    assert r.status_code == 400
    r = await client.post("/merchant/payouts", json={"currency": "usd", "method": "manual", "affiliate_ids": [S["aff_id"]], "reference": "PayPal 7XK"}, headers=auth(S["owner"]))
    assert r.status_code == 200 and r.json()["status"] == "paid" and r.json()["reference"] == "PayPal 7XK"

    # Undo puts the commissions back in the payable pool
    assert (await client.post(f"/merchant/payouts/{r.json()['id']}/undo", headers=auth(S["owner"]))).status_code == 200
    assert (await client.post(f"/merchant/payouts/{r.json()['id']}/undo", headers=auth(S["owner"]))).status_code == 400
    p = (await client.get("/merchant/payouts", headers=auth(S["owner"]))).json()
    assert [l["amount_cents"] for l in p["payable"]] == [2250 + 1500]

    r = await client.post("/merchant/payouts", json={"currency": "usd", "method": "manual"}, headers=auth(S["owner"]))
    assert r.status_code == 200 and r.json()["status"] == "paid"
    S["manual_payout"] = r.json()["id"]
    csv = (await client.get(f"/merchant/payouts/{S['manual_payout']}/csv", headers=auth(S["owner"]))).text
    assert "Jane Creator,creator@youtube.example,paypal,jane.pp@example.com,37.50,USD,2" in csv
    assert (await client.post("/merchant/payouts", json={"currency": "usd", "method": "manual"}, headers=auth(S["owner"]))).status_code == 400


async def test_refund_after_payout_claws_back_and_nets(client, db):
    r = await send_event(client, hook_url(), "whsec_merchant", "charge.refunded", {"id": "ch_2", "payment_intent": "pi_2", "amount": 5000, "amount_refunded": 5000})
    assert r.json()["outcome"] == "clawback -1500"
    # Clearing the self-referral releases its 3000; net payable = 3000 - 1500
    await client.post(f"/merchant/referrals/{S['self_ref']}/clear", headers=auth(S["owner"]))
    await age_commissions(db)
    p = (await client.get("/merchant/payouts", headers=auth(S["owner"]))).json()
    assert p["payable"] == []  # 15.00 net is under the 20.00 minimum
    r = await client.put(
        f"/merchant/campaigns/{S['campaign_id']}",
        json={"name": "Default", "rule_type": "percent", "percent": 30, "duration_mode": "months", "months": 12, "hold_days": 30, "min_payout_cents": 1000, "stripe_coupon_id": "coupon_20"},
        headers=auth(S["owner"]),
    )
    assert r.status_code == 200, r.text
    p = (await client.get("/merchant/payouts", headers=auth(S["owner"]))).json()
    assert [l["amount_cents"] for l in p["payable"]] == [1500]
    assert p["payable"][0]["payouts_enabled"] is False


async def test_stripe_payout_via_connect(client, db, fakes):
    r = await client.post("/payout-account/onboard", json={"country": "US"}, headers=auth(S["aff"]))
    assert r.json()["url"] == "https://connect.stripe.test/acct_aff1"
    assert (await client.post("/merchant/payouts", json={"currency": "usd", "method": "stripe"}, headers=auth(S["owner"]))).status_code == 400
    fakes["platform"].enabled.add("acct_aff1")
    assert (await client.post("/payout-account/refresh", headers=auth(S["aff"]))).json()["payouts_enabled"]

    r = await client.post("/merchant/payouts", json={"currency": "usd", "method": "stripe"}, headers=auth(S["owner"]))
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["status"] == "awaiting_funding" and po["total_cents"] == 1500 and po["funding_url"]
    session = {"id": po["funding_session_id"], "metadata": {"kr_payout": po["id"]}}
    r = await send_event(client, "/webhooks/platform", "whsec_platform", "checkout.session.completed", session)
    assert r.json()["outcome"] == "payout paid"
    assert fakes["platform"].transfers == [{"amount": 1500, "currency": "usd", "destination": "acct_aff1", "source": "ch_funding", "key": f"{po['id']}:{S['aff_id']}"}]
    # Webhook retry does not transfer twice
    r = await send_event(client, "/webhooks/platform", "whsec_platform", "checkout.session.completed", session)
    assert r.json()["outcome"] == "not awaiting funding" and len(fakes["platform"].transfers) == 1

    d = (await client.get(f"/portal/{S['aff_id']}", headers=auth(S["aff"]))).json()
    assert d["totals"]["usd"] == {"in_hold": 0, "payable": 0, "paid": 2250 + 1500 + 3000 - 1500}
    assert d["leads"] == 3 and d["customers"] == 3 and d["clicks"] == 1


async def test_commission_window_ends(client, db):
    await db.referrals.update_one({"_id": S["ref_id"]}, {"$set": {"first_paid_at": datetime.now(UTC) - timedelta(days=400)}})
    r = await send_event(client, hook_url(), "whsec_merchant", "invoice.paid", {"id": "in_late", "customer": "cus_1", "amount_paid": 11000, "currency": "usd", "status_transitions": {"paid_at": int(time.time())}})
    assert r.json()["outcome"] == "no commission: outside the 12-month commission window"


async def test_overview_and_tenant_isolation(client):
    o = (await client.get("/merchant/overview", headers=auth(S["owner"]))).json()
    assert o["affiliates"] == 2 and o["customers"] == 3 and o["installed"]
    # The affiliate has no merchant workspace and can't read Acme's data
    assert (await client.get("/merchant/commissions", headers=auth(S["aff"]))).status_code == 404
