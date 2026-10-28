"""One-off payments made straight through the Payment Intents API (Stripe Elements),
with no invoice and no Checkout Session."""

import time

from app.services.stripe_events import catch_up_payment_intents
from tests.conftest import send_event


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


def pi(pi_id, customer, cents, currency="usd"):
    return {"id": pi_id, "object": "payment_intent", "status": "succeeded", "customer": customer, "amount": cents, "amount_received": cents, "currency": currency, "created": int(time.time()), "metadata": {}}


async def test_payment_intent_earns_once(client, db, fakes):
    owner = await signup(client, db, "owner@pi.example", "Pia")
    r = (await client.post("/merchant", json={"name": "Pico", "website": "https://pico.example"}, headers=auth(owner))).json()
    mid, sk = r["merchant"]["id"], {"authorization": f"Bearer {r['secret_key']}"}
    assert (await client.post("/merchant/stripe", json={"restricted_key": "rk_test_pico"}, headers=auth(owner))).status_code == 200
    await client.post("/v1/affiliates", json={"email": "aff@pi.example", "name": "Al", "token": "alpi", "send_welcome_email": False}, headers=sk)
    for n in range(1, 5):
        await client.post("/v1/referrals", json={"via": "alpi", "email": f"buyer{n}@else.example", "stripe_customer_id": f"cus_pi{n}"}, headers=sk)
    hook = f"/webhooks/stripe/{mid}"
    async def commissions():
        return await db.commissions.find({"merchant_id": mid}).to_list(None)

    # A lifetime purchase: the referral converts and earns the campaign's 30%.
    r = await send_event(client, hook, "whsec_merchant", "payment_intent.succeeded", pi("pi_life", "cus_pi1", 10000))
    assert r.json()["outcome"] == "commission 3000 usd", r.text
    ref = await db.referrals.find_one({"merchant_id": mid, "stripe_customer_id": "cus_pi1"})
    assert ref["status"] == "customer" and ref["first_paid_at"]
    [c] = await commissions()
    assert c["source_key"] == "pi:pi_life" and c["payment_intent_id"] == "pi_life"
    # Stripe sending it again earns nothing.
    assert (await send_event(client, hook, "whsec_merchant", "payment_intent.succeeded", pi("pi_life", "cus_pi1", 10000))).json()["outcome"] == "already earned"

    # A subscription invoice's payment intent leaves it to invoice.paid.
    fakes["merchant"].invoice_pi["in_sub"] = "pi_sub"
    assert (await send_event(client, hook, "whsec_merchant", "payment_intent.succeeded", pi("pi_sub", "cus_pi2", 5000))).json()["outcome"].startswith("invoice payment")
    # So does a Checkout payment, and when the session lands it earns once.
    fakes["merchant"].session_pi["cs_one"] = "pi_cs"
    assert (await send_event(client, hook, "whsec_merchant", "payment_intent.succeeded", pi("pi_cs", "cus_pi3", 5000))).json()["outcome"].startswith("checkout payment")
    assert len(await commissions()) == 1

    # A payment intent that already earned under another key never earns again.
    fakes["merchant"].session_pi.pop("cs_one")
    assert (await send_event(client, hook, "whsec_merchant", "payment_intent.succeeded", pi("pi_cs", "cus_pi3", 5000))).json()["outcome"] == "commission 1500 usd"
    session = {"id": "cs_late", "mode": "payment", "payment_status": "paid", "customer": "cus_pi3", "amount_total": 5000, "currency": "usd", "payment_intent": "pi_cs", "created": int(time.time())}
    assert (await send_event(client, hook, "whsec_merchant", "checkout.session.completed", session)).json()["outcome"] == "already earned"

    # Refunding it voids the commission, as for invoices.
    r = await send_event(client, hook, "whsec_merchant", "charge.refunded", {"id": "ch_life", "payment_intent": "pi_life", "amount": 10000, "amount_refunded": 10000})
    assert r.json()["outcome"] == "voided"

    # The catch-up replays payments made before Kickrail listened, once, and updates the webhook.
    fakes["merchant"].payment_intents = [pi("pi_missed", "cus_pi4", 20000), pi("pi_life", "cus_pi1", 10000), pi("pi_stranger", "cus_nobody", 999)]
    await db.merchants.update_many({"_id": {"$ne": mid}}, {"$set": {"stripe.pi_caught_up_at": 1}})
    assert await catch_up_payment_intents(db, lambda m: fakes["merchant"]) == 1
    m = await db.merchants.find_one({"_id": mid})
    assert m["stripe"]["pi_catch_up"] == {"commission": 1, "already": 1, "no": 1}
    assert "we_1" in fakes["merchant"].webhook_updates
    assert await db.commissions.find_one({"merchant_id": mid, "source_key": "pi:pi_missed", "amount_cents": 6000})
    assert await catch_up_payment_intents(db, lambda m: fakes["merchant"]) == 0
    fakes["merchant"].payment_intents = []
