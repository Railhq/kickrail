"""The program features around the core flow: links and codes, overrides, product
rules, lead bounties, emails, webhooks, the /v1 API, PayPal, tax forms, team, view-as."""

import hashlib
import hmac
import re
import time
from datetime import UTC, datetime, timedelta

import pytest

from app import deps
from app.services import outbox

from app.db import get_db

from .conftest import send_event

S = {}
pytestmark = pytest.mark.asyncio(loop_scope="session")


def auth(token):
    return {"authorization": f"Bearer {token}"}


def owner():
    return auth(S["owner"])


def api():
    return {"authorization": f"Bearer {S['sk']}"}


async def signup(client, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name}, headers={"x-forwarded-for": f"10.9.0.{len(S) + 1}"})
    assert r.status_code == 200, r.text
    await (await get_db()).users.update_one({"email": email}, {"$set": {"email_verified": True}})  # as if they clicked the link
    return r.json()["token"]


class FakePayPal:
    def __init__(self):
        self.batches: dict[str, list[dict]] = {}
        self.state: dict[str, str] = {}

    async def verify(self):
        return None

    async def create_batch(self, sender_batch_id, subject, items):
        self.batches[sender_batch_id] = items
        return f"PB_{sender_batch_id}"

    async def batch(self, batch_id):
        items = self.batches[batch_id.removeprefix("PB_")]
        return {
            "status": "SUCCESS",
            "items": [{"sender_item_id": i["sender_item_id"], "status": self.state.get(i["email"], "SUCCESS"), "item_id": f"PI_{n}", "error": None} for n, i in enumerate(items)],
        }


@pytest.fixture(scope="module", autouse=True)
def fakes_for_module(fakes, monkeypatch_module):
    from app.main import app
    from app.routers import developers, merchant

    pp = FakePayPal()
    fakes["paypal"] = pp
    app.dependency_overrides[deps.paypal_factory] = lambda: (lambda m: pp)
    app.dependency_overrides[deps.paypal_key_client] = lambda: (lambda cid, secret, mode: pp)
    sent: list[tuple[str, str, dict]] = []
    fakes["posts"] = sent

    async def post(url, body, headers):
        sent.append((url, body, headers))
        return (500, "boom") if "fail" in url else (200, "ok")

    monkeypatch_module.setattr(outbox, "http_post", post)
    monkeypatch_module.setattr(developers.socket, "getaddrinfo", lambda host, *a, **k: [(0, 0, 0, "", ("10.1.2.3" if "internal" in host else "93.184.216.34", 443))])
    monkeypatch_module.setattr(merchant, "_cname_ok", lambda host: (host.startswith("partners."), "verified" if host.startswith("partners.") else "no CNAME"))

    async def https_ok(host):
        return True, "HTTPS is working"

    monkeypatch_module.setattr(merchant, "_https_ok", https_ok)
    yield
    app.dependency_overrides.pop(deps.paypal_factory, None)
    app.dependency_overrides.pop(deps.paypal_key_client, None)


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


async def test_setup(client):
    S["owner"] = await signup(client, "owner@globex.com", "Globex Owner")
    r = await client.post("/merchant", json={"name": "Globex", "website": "https://globex.com"}, headers=owner())
    assert r.status_code == 200, r.text
    m = r.json()
    S["merchant_id"], S["pk"], S["sk"] = m["merchant"]["id"], m["merchant"]["public_key"], m["secret_key"]
    assert (await client.post("/merchant/stripe", json={"restricted_key": "rk_test_globex"}, headers=owner())).status_code == 200
    S["campaign_id"] = (await client.get("/merchant/campaigns", headers=owner())).json()[0]["id"]
    r = await client.put(
        f"/merchant/campaigns/{S['campaign_id']}",
        json={
            "name": "Default", "rule_type": "percent", "percent": 20, "duration_mode": "forever", "hold_days": 30, "min_payout_cents": 0, "stripe_coupon_id": "coupon_20",
            "lead_bounty_cents": 300, "lead_bounty_currency": "usd",
            "product_rules": [
                {"match": "product", "id": "prod_ebook", "label": "Ebook", "rule": {"type": "percent", "percent": 50}},
                {"match": "price", "id": "price_free", "rule": {"type": "none"}},
            ],
        },
        headers=owner(),
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["description"] == "20% of every payment, for life, plus 3.00 USD per signup"
    assert [p["description"] for p in c["product_rules"]] == ["50%", "no commission"]


async def test_branding_and_email_toggles(client):
    r = await client.put("/merchant/branding", json={"logo_url": "https://globex.com/logo.png", "color": "#7c3aed", "headline": "Earn with Globex", "welcome_message": "Ping us in Slack."}, headers=owner())
    assert r.status_code == 200, r.text
    assert r.json()["branding"]["color"] == "#7c3aed"
    r = await client.patch("/merchant", json={"emails": {"commission": False}}, headers=owner())
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["emails"] == {"welcome": True, "approved": True, "commission": False, "payout": True, "new_affiliate": True, "self_referral": True}
    assert (await client.patch("/merchant", json={"emails": {"nope": True}}, headers=owner())).status_code == 422
    prog = (await client.get("/programs/globex")).json()
    assert prog["branding"]["headline"] == "Earn with Globex" and "plus 3.00 USD per signup" in prog["terms"]


async def test_join_sends_branded_welcome_and_webhook(client, db):
    S["aff"] = await signup(client, "jane@creators.example", "Jane")
    r = await client.post("/programs/globex/join", json={}, headers=auth(S["aff"]))
    assert r.status_code == 200, r.text
    S["aff_id"], S["token"] = r.json()["id"], r.json()["token"]
    mail = await db.emails.find_one({"merchant_id": S["merchant_id"], "to": "jane@creators.example", "kind": "welcome"})
    assert mail["subject"] == "Welcome to the Globex affiliate program"
    assert "Ping us in Slack." in mail["text"] and "#7c3aed" in mail["html"] and mail["from"].startswith("Globex via Kickrail <")
    assert mail["reply_to"] == "owner@globex.com"
    assert await db.events.find_one({"merchant_id": S["merchant_id"], "type": "affiliate.created", "data.id": S["aff_id"]})
    # Without SMTP the email is logged, never sent.
    await outbox.deliver_due(db)
    assert (await db.emails.find_one({"_id": mail["_id"]}))["status"] == "logged"


async def test_extra_links_and_codes(client, db, fakes):
    r = await client.post(f"/portal/{S['aff_id']}/links", json={"token": "jane-pricing", "landing_url": "https://globex.com/pricing?x=1", "label": "Pricing"}, headers=auth(S["aff"]))
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "https://globex.com/pricing?x=1&via=jane-pricing"
    S["link_id"] = r.json()["id"]
    bad = await client.post(f"/portal/{S['aff_id']}/links", json={"token": "jane-evil", "landing_url": "https://evil.example/"}, headers=auth(S["aff"]))
    assert bad.status_code == 422
    taken = await client.post(f"/portal/{S['aff_id']}/links", json={"token": S["token"]}, headers=auth(S["aff"]))
    assert taken.status_code == 409

    r = await client.post(f"/merchant/affiliates/{S['aff_id']}/codes", json={"code": "janepod"}, headers=owner())
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "JANEPOD" and r.json()["redeemable_at_checkout"]
    assert ("coupon_20", "JANEPOD") in fakes["merchant"].promotion_codes
    assert (await client.post(f"/merchant/affiliates/{S['aff_id']}/codes", json={"code": "JANE"}, headers=owner())).status_code == 409

    # A click on the extra link is tracked for the same affiliate.
    r = await client.post("/track/click", content=f'{{"key":"{S["pk"]}","id":"kr_globexclick000000001","token":"jane-pricing","url":"https://globex.com/pricing"}}')
    assert r.status_code == 204
    click = await db.clicks.find_one({"_id": "kr_globexclick000000001"})
    assert click["affiliate_id"] == S["aff_id"] and click["token"] == "jane-pricing"


async def test_lead_bounty_on_signup(client, db):
    r = await client.post("/v1/referrals", json={"referral": "kr_globexclick000000001", "email": "buyer1@corp.example", "stripe_customer_id": "cus_g1"}, headers=api())
    assert r.status_code == 200 and r.json()["referred"], r.text
    S["ref1"] = r.json()["referral"]["id"]
    lead = await db.commissions.find_one({"referral_id": S["ref1"], "kind": "lead"})
    assert lead["amount_cents"] == 300 and lead["currency"] == "usd" and lead["source_key"] == f"lead:{S['ref1']}"
    # Reporting the same signup again pays nothing extra.
    await client.post("/v1/referrals", json={"email": "buyer1@corp.example"}, headers=api())
    assert await db.commissions.count_documents({"referral_id": S["ref1"], "kind": "lead"}) == 1


def invoice(inv_id, customer, lines):
    paid = int(time.time())
    data = [{"amount": amt, "pricing": {"price_details": {"price": price, "product": prod}}} for amt, prod, price in lines]
    return {"id": inv_id, "customer": customer, "amount_paid": sum(a for a, _, _ in lines), "currency": "usd", "status_transitions": {"paid_at": paid}, "created": paid, "lines": {"data": data}}


async def test_product_rules(client, db):
    hook = f"/webhooks/stripe/{S['merchant_id']}"
    # 50% of the ebook line, nothing for the free price, 20% (campaign) for the rest.
    inv = invoice("in_g1", "cus_g1", [(4000, "prod_ebook", "price_ebook"), (3000, "prod_plan", "price_free"), (6000, "prod_plan", "price_plan")])
    r = await send_event(client, hook, "whsec_merchant", "invoice.paid", inv)
    assert r.json()["outcome"] == "commission 3200 usd", r.text


async def test_rate_override_beats_campaign_not_product_rules(client, db):
    r = await client.patch(f"/merchant/affiliates/{S['aff_id']}", json={"rate_override": {"type": "percent", "percent": 35}}, headers=owner())
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/portal/{S['aff_id']}", headers=auth(S["aff"]))).json()
    assert detail["program"]["terms"].startswith("35% of every payment")
    await client.post("/v1/referrals", json={"via": S["token"], "email": "buyer2@corp.example", "stripe_customer_id": "cus_g2"}, headers=api())
    inv = invoice("in_g2", "cus_g2", [(4000, "prod_ebook", "price_ebook"), (6000, "prod_plan", "price_plan")])
    r = await send_event(client, f"/webhooks/stripe/{S['merchant_id']}", "whsec_merchant", "invoice.paid", inv)
    assert r.json()["outcome"] == "commission 4100 usd"  # 2000 ebook + 35% of 6000
    # The commission email is switched off for this program.
    assert not await db.emails.find_one({"merchant_id": S["merchant_id"], "kind": "commission"})
    r = await client.patch(f"/merchant/affiliates/{S['aff_id']}", json={"clear_rate_override": True}, headers=owner())
    assert r.json().get("rate_override") is None


async def test_view_as_matches_portal(client):
    mine = (await client.get(f"/portal/{S['aff_id']}", headers=auth(S["aff"]))).json()
    seen = (await client.get(f"/merchant/affiliates/{S['aff_id']}/view", headers=owner())).json()
    assert seen["affiliate"] == {"name": "Jane", "email": "jane@creators.example"}
    seen.pop("affiliate")
    # Except whom each commission was for: the merchant gets the referral, the affiliate a masked email.
    for a, b in zip(seen["commissions"], mine["commissions"]):
        if a["customer"]:
            assert a["customer"]["referral_id"] and "referral_id" not in b["customer"]
            assert b["customer"]["email"] in (None, a["customer"]["email"][:2] + "***@" + a["customer"]["email"].split("@")[1])
        a.pop("customer"), b.pop("customer")
    assert seen == mine
    other = await signup(client, "nosy@else.example", "Nosy")
    assert (await client.get(f"/merchant/affiliates/{S['aff_id']}/view", headers=auth(other))).status_code in (403, 404)


async def test_webhook_endpoints_sign_and_retry(client, db, fakes):
    assert (await client.post("/merchant/webhooks", json={"url": "http://hooks.globex.com/kr"}, headers=owner())).status_code == 422
    assert (await client.post("/merchant/webhooks", json={"url": "https://internal.globex.com/kr"}, headers=owner())).status_code == 422
    assert (await client.post("/merchant/webhooks", json={"url": "https://hooks.globex.com/kr", "events": ["nope.event"]}, headers=owner())).status_code == 422
    r = await client.post("/merchant/webhooks", json={"url": "https://hooks.globex.com/kr", "events": ["affiliate.updated", "commission.created"]}, headers=owner())
    assert r.status_code == 200, r.text
    ep, secret = r.json()["id"], r.json()["secret"]
    bad = (await client.post("/merchant/webhooks", json={"url": "https://fail.globex.com/kr"}, headers=owner())).json()["id"]

    await client.patch(f"/merchant/affiliates/{S['aff_id']}", json={"metadata": {"crm_id": "42"}}, headers=owner())
    fakes["posts"].clear()
    await outbox.deliver_due(db)
    urls = [u for u, _, _ in fakes["posts"]]
    assert "https://hooks.globex.com/kr" in urls and "https://fail.globex.com/kr" in urls
    url, body, headers = next(p for p in fakes["posts"] if p[0] == "https://hooks.globex.com/kr")
    assert headers["kickrail-event"] == "affiliate.updated"
    t, v1 = (kv.split("=", 1)[1] for kv in headers["kickrail-signature"].split(","))
    assert v1 == hmac.new(secret.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
    assert '"crm_id":"42"' in body

    failed = await db.webhook_deliveries.find_one({"endpoint_id": bad})
    assert failed["status"] == "pending" and failed["attempts"] == 1 and failed["next_attempt_at"] > datetime.now(UTC)
    log = (await client.get(f"/merchant/webhooks/{bad}/deliveries", headers=owner())).json()
    assert log[0]["response_status"] == 500 and log[0]["payload"]
    assert (await client.post(f"/merchant/webhooks/deliveries/{failed['_id']}/retry", headers=owner())).status_code == 200

    r = await client.post(f"/merchant/webhooks/{ep}/test", headers=owner())
    assert r.json()["ok"] and r.json()["type"] == "ping"
    assert (await client.delete(f"/merchant/webhooks/{bad}", headers=owner())).status_code == 200


async def test_v1_api(client, db):
    r = await client.get("/v1/affiliates", headers=api())
    assert r.status_code == 200
    assert [a["id"] for a in r.json()["data"]] == [S["aff_id"]]
    a = r.json()["data"][0]
    assert a["object"] == "affiliate" and [l["token"] for l in a["links"]] == ["jane-pricing"] and [c["code"] for c in a["codes"]] == ["JANEPOD"]

    r = await client.post("/v1/affiliates", json={"email": "Podcaster@Shows.example", "name": "Pat Podcaster", "token": "patpod", "rate_override": {"type": "flat", "flat_cents": 2500}, "metadata": {"crm_id": "77"}}, headers=api())
    assert r.status_code == 200, r.text
    pat = r.json()
    assert pat["created"] and pat["token"] == "patpod" and pat["email"] == "podcaster@shows.example" and pat["rate_override"] == {"type": "flat", "cents": 2500, "currency": "usd"}
    S["pat_id"] = pat["id"]
    assert (await client.post("/v1/affiliates", json={"email": "other@shows.example", "name": "X", "token": "patpod"}, headers=api())).status_code == 409

    page1 = (await client.get("/v1/affiliates?limit=1", headers=api())).json()
    assert page1["has_more"] and page1["data"][0]["id"] == S["pat_id"]
    page2 = (await client.get(f"/v1/affiliates?limit=1&starting_after={S['pat_id']}", headers=api())).json()
    assert [a["id"] for a in page2["data"]] == [S["aff_id"]] and not page2["has_more"]
    assert (await client.get("/v1/affiliates?email=podcaster@shows.example", headers=api())).json()["data"][0]["id"] == S["pat_id"]

    r = await client.patch(f"/v1/affiliates/{S['pat_id']}", json={"status": "pending"}, headers=api())
    assert r.json()["status"] == "pending"
    comms = (await client.get(f"/v1/commissions?affiliate_id={S['aff_id']}", headers=api())).json()["data"]
    assert sorted(c["kind"] for c in comms) == ["lead", "lead", "sale", "sale"]
    assert (await client.get(f"/v1/commissions/{comms[0]['id']}", headers=api())).json()["id"] == comms[0]["id"]
    refs = (await client.get("/v1/referrals?status=customer", headers=api())).json()["data"]
    assert len(refs) == 2
    assert (await client.get("/v1/campaigns", headers=api())).json()["data"][0]["object"] == "campaign"
    assert (await client.get("/v1/affiliates", headers={"authorization": "Bearer sk_kr_wrong"})).status_code == 401


async def test_api_created_affiliate_claims_with_link_only(client, db):
    mail = await db.emails.find_one({"to": "podcaster@shows.example", "kind": "welcome"})
    token = re.search(r"/claim\?token=(\w+)", mail["text"]).group(1)
    # Knowing the email is not enough to take the account.
    r = await client.post("/auth/signup", json={"email": "podcaster@shows.example", "password": "hijack-attempt", "name": "Mallory"})
    assert r.status_code == 409 and "invited" in r.json()["detail"]
    assert (await client.post("/auth/login", json={"email": "podcaster@shows.example", "password": "anything"})).status_code == 401
    r = await client.post("/auth/claim", json={"token": token, "password": "pat-secret-pw"})
    assert r.status_code == 200, r.text
    assert (await client.post("/auth/claim", json={"token": token, "password": "again-again"})).status_code == 400
    r = await client.post("/auth/login", json={"email": "podcaster@shows.example", "password": "pat-secret-pw"})
    assert r.status_code == 200
    portal = (await client.get("/portal", headers=auth(r.json()["token"]))).json()
    assert portal["programs"][0]["program"]["name"] == "Globex"


async def age(db):
    await db.commissions.update_many({"merchant_id": S["merchant_id"]}, {"$set": {"due_at": datetime.now(UTC) - timedelta(days=1)}})


async def test_tax_form_gates_payouts(client, db):
    await age(db)
    assert (await client.patch("/merchant", json={"require_tax_form": True}, headers=owner())).status_code == 200
    due = (await client.get("/merchant/payouts", headers=owner())).json()["payable"]
    jane = next(l for l in due if l["affiliate_id"] == S["aff_id"])
    assert jane["needs_tax_form"]
    assert (await client.post("/merchant/payouts", json={"currency": "usd", "method": "manual", "affiliate_ids": [S["aff_id"]]}, headers=owner())).status_code == 400

    form = {"form": "w9", "legal_name": "Jane Q Creator", "classification": "individual", "country": "US", "address": "1 Main St, Austin TX 78701", "tin": "123-45-6789", "signature": "Jane Q Creator", "certify": True}
    assert (await client.put("/tax-info", json=form | {"country": "DE"}, headers=auth(S["aff"]))).status_code == 422
    assert (await client.put("/tax-info", json=form | {"certify": False}, headers=auth(S["aff"]))).status_code == 422
    r = await client.put("/tax-info", json=form, headers=auth(S["aff"]))
    assert r.status_code == 200, r.text
    assert r.json()["tax_info"]["tin_last4"] == "6789" and "tin" not in r.json()["tax_info"] and "tin_enc" not in r.json()["tax_info"]
    stored = await db.users.find_one({"email": "jane@creators.example"})
    assert "123456789" not in str(stored["tax_info"])
    tax = (await client.get("/merchant/tax", headers=owner())).json()
    assert next(a for a in tax["affiliates"] if a["affiliate_id"] == S["aff_id"])["form"] == "w9"


async def test_paypal_payout(client, db, fakes):
    assert (await client.post("/merchant/payouts", json={"currency": "usd", "method": "paypal"}, headers=owner())).status_code == 400  # not connected
    r = await client.put("/merchant/paypal", json={"client_id": "AbCdEf1234567890", "secret": "s3cr3t-s3cr3t", "mode": "sandbox"}, headers=owner())
    assert r.status_code == 200 and r.json()["paypal"]["mode"] == "sandbox" and "secret" not in str(r.json()["paypal"])
    # No PayPal email saved yet.
    assert (await client.post("/merchant/payouts", json={"currency": "usd", "method": "paypal"}, headers=owner())).status_code == 400
    await client.put("/payout-account/details", json={"method": "paypal", "value": "jane@paypal.example"}, headers=auth(S["aff"]))
    csv = (await client.get("/merchant/payouts/paypal.csv?currency=usd", headers=owner())).text
    assert csv.startswith("jane@paypal.example,")

    r = await client.post("/merchant/payouts", json={"currency": "usd", "method": "paypal"}, headers=owner())
    assert r.status_code == 200, r.text
    payout = r.json()
    assert payout["status"] == "processing" and payout["paypal_batch_id"] == f"PB_{payout['id']}"
    sent = fakes["paypal"].batches[payout["id"]]
    assert [(i["email"], i["amount_cents"]) for i in sent] == [("jane@paypal.example", 300 + 300 + 3200 + 4100)]
    assert (await client.post(f"/merchant/payouts/{payout['id']}/sync", headers=owner())).json()["status"] == "paid"
    assert all(c["status"] == "paid" for c in await db.commissions.find({"affiliate_id": S["aff_id"]}).to_list(None))
    mail = await db.emails.find_one({"to": "jane@creators.example", "kind": "payout"})
    assert "to your PayPal account" in mail["text"]
    assert await db.events.count_documents({"merchant_id": S["merchant_id"], "type": "payout.paid"}) == 1


async def test_team_invites(client, db):
    r = await client.post("/merchant/team/invites", json={"email": "ops@globex.com"}, headers=owner())
    assert r.status_code == 200, r.text
    mail = await db.emails.find_one({"to": "ops@globex.com", "kind": "team_invite"})
    token = re.search(r"/invite/(\w+)", mail["text"]).group(1)
    info = (await client.get(f"/auth/invites/{token}")).json()
    assert info["merchant"]["name"] == "Globex" and not info["has_account"]

    wrong = await signup(client, "someone@else.example", "Wrong")
    assert (await client.post(f"/auth/invites/{token}/accept", headers=auth(wrong))).status_code == 403
    ops = await signup(client, "ops@globex.com", "Ops")
    assert (await client.post(f"/auth/invites/{token}/accept", headers=auth(ops))).status_code == 200
    assert (await client.post(f"/auth/invites/{token}/accept", headers=auth(ops))).status_code == 404
    assert (await client.get("/merchant", headers=auth(ops))).json()["id"] == S["merchant_id"]
    team = (await client.get("/merchant/team", headers=owner())).json()
    assert sorted(m["email"] for m in team["members"]) == ["ops@globex.com", "owner@globex.com"]

    # Members run the program, but full TINs are owner-only.
    assert (await client.get(f"/merchant/tax/1099.csv?year={datetime.now(UTC).year}", headers=auth(ops))).status_code == 403
    csv = (await client.get(f"/merchant/tax/1099.csv?year={datetime.now(UTC).year}", headers=owner())).text
    assert csv.splitlines()[0].startswith("legal_name,") and "123456789" not in csv  # Jane was paid 79.00, under the 600 threshold
    owner_id = team["owner_id"]
    assert (await client.delete(f"/merchant/team/members/{owner_id}", headers=auth(ops))).status_code == 400
    ops_id = next(m["id"] for m in team["members"] if m["email"] == "ops@globex.com")
    assert (await client.delete(f"/merchant/team/members/{ops_id}", headers=owner())).status_code == 200
    assert (await client.get("/merchant", headers=auth(ops))).status_code in (403, 404)


async def test_custom_domain(client, db):
    r = await client.post("/merchant/domains", json={"host": "https://Partners.Globex.com/"}, headers=owner())
    assert r.status_code == 200, r.text
    d, m = r.json()["domain"], r.json()["merchant"]
    assert d["host"] == "partners.globex.com" and d["verified"] and d["https"] is True
    assert m["portal_domains"][0]["primary"] and m["portal_url"] == "https://partners.globex.com" and m["join_url"] == "https://partners.globex.com/"
    info = (await client.get("/domains/partners.globex.com")).json()
    assert info["slug"] == "globex" and info["branding"]["color"] == "#7c3aed"
    assert (await client.get("/domains/unknown.example")).status_code == 404
    # The portal proxy only gets certificates for verified domains.
    assert (await client.get("/tls/ask?domain=partners.globex.com")).status_code == 200
    assert (await client.get("/tls/ask?domain=unknown.example")).status_code == 404
    # Several domains (Growth trial: 3). Both serve the portal; links use the primary.
    assert (await client.post("/merchant/domains", json={"host": "partners.globex.dev"}, headers=owner())).status_code == 200
    assert (await client.post("/merchant/domains", json={"host": "partners.globex.dev"}, headers=owner())).status_code == 409
    assert (await client.get("/domains/partners.globex.dev")).json()["slug"] == "globex"
    m = (await client.post("/merchant/domains/partners.globex.dev/primary", headers=owner())).json()
    assert m["portal_url"] == "https://partners.globex.dev"
    assert (await client.post("/merchant/domains", json={"host": "aff.globex.io"}, headers=owner())).status_code == 200
    r = await client.post("/merchant/domains", json={"host": "partners.globex.net"}, headers=owner())
    assert r.status_code == 402 and "Scale" in r.json()["detail"]
    # Downgraded to Starter (1 domain): every domain keeps working, extras are flagged, none can be added.
    await db.merchants.update_one({"slug": "globex"}, {"$set": {"plan": {"id": "starter", "status": "active", "stripe_subscription": "sub_x"}}})
    m = (await client.get("/merchant", headers=owner())).json()
    assert [x["over_limit"] for x in m["portal_domains"]] == [False, True, True] and m["domain_limit"] == 1
    assert (await client.get("/tls/ask?domain=partners.globex.dev")).status_code == 200
    assert (await client.post("/merchant/domains", json={"host": "partners.globex.net"}, headers=owner())).status_code == 402
    # Removing the primary hands it to the next verified domain.
    assert (await client.delete("/merchant/domains/partners.globex.dev", headers=owner())).status_code == 200
    m = (await client.get("/merchant", headers=owner())).json()
    assert m["portal_url"] == "https://partners.globex.com" and [x["host"] for x in m["portal_domains"]] == ["partners.globex.com", "aff.globex.io"]
    assert (await client.delete("/merchant/domains/aff.globex.io", headers=owner())).status_code == 200
    await db.merchants.update_one({"slug": "globex"}, {"$set": {"plan": {"id": "growth", "status": "trialing", "trial_ends_at": datetime.now(UTC) + timedelta(days=14)}}})
    other = await signup(client, "rival@initech.example", "Rival")
    await client.post("/merchant", json={"name": "Initech", "website": "https://initech.example"}, headers=auth(other))
    assert (await client.post("/merchant/domains", json={"host": "partners.globex.com"}, headers=auth(other))).status_code == 409
    r = await client.post("/merchant/domains", json={"host": "aff.initech.example"}, headers=auth(other))
    assert r.json()["domain"]["verified"] is False and r.json()["merchant"]["portal_url"] == "https://kickrail.test"
    assert (await client.get("/tls/ask?domain=aff.initech.example")).status_code == 404


async def test_brevo_transport_and_test_domain_guard(db, monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "brevo_api_key", "xkeysib-test")
    monkeypatch.setattr(s, "mail_via", "")
    monkeypatch.setattr(s, "mail_from", "Affiliates <noreply@codemia.io>")
    calls = []

    class FakeClient:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers):
            calls.append((url, json, headers))
            return type("R", (), {"status_code": 201, "text": "{}"})()

    monkeypatch.setattr(outbox.httpx, "AsyncClient", FakeClient)
    now = datetime.now(UTC)
    await outbox.queue_email(db, "jane@realmail.dev", "Hi", "Body", "<p>Body</p>", kind="welcome", from_name="Codemia", reply_to="Owner <owner@codemia.io>")
    await outbox.queue_email(db, "fake@example.com", "Hi", "Body", kind="welcome", from_name="Codemia")
    real = await db.emails.find_one({"to": "jane@realmail.dev"})
    fake = await db.emails.find_one({"to": "fake@example.com"})
    assert await outbox.deliver_email(db, real, now) == "sent"
    assert await outbox.deliver_email(db, fake, now) == "logged"
    assert len(calls) == 1
    url, body, headers = calls[0]
    assert url == "https://api.brevo.com/v3/smtp/email" and headers["api-key"] == "xkeysib-test"
    assert body["sender"] == {"name": "Codemia", "email": "noreply@codemia.io"}
    assert body["to"] == [{"email": "jane@realmail.dev"}] and body["replyTo"] == {"email": "owner@codemia.io"}
    assert body["htmlContent"] == "<p>Body</p>" and "welcome" in body["tags"]


async def test_one_account_runs_several_programs(client, db):
    tok = await signup(client, "multi@initech.example", "Multi")
    h = auth(tok)
    first = (await client.post("/merchant", json={"name": "Initech", "website": "https://initech.example"}, headers=h)).json()["merchant"]
    second = (await client.post("/merchant", json={"name": "Initrode", "website": "https://initrode.example"}, headers=h)).json()["merchant"]
    on = lambda mid: {**h, "x-kickrail-program": mid}  # noqa: E731

    me = (await client.get("/auth/me", headers=h)).json()
    assert [p["name"] for p in me["merchants"]] == ["Initech", "Initrode"] and me["merchant"]["id"] == first["id"]
    assert (await client.get("/auth/me", headers=on(second["id"]))).json()["merchant"]["id"] == second["id"]
    assert (await client.get("/merchant", headers=h)).json()["id"] == first["id"]
    assert (await client.get("/merchant", headers=on(second["id"]))).json()["id"] == second["id"]
    # Someone else's program id falls back to your own rather than leaking theirs.
    assert (await client.get("/merchant", headers=on(S["merchant_id"]))).json()["id"] == first["id"]

    # Changes land only in the selected program.
    await client.patch("/merchant", json={"name": "Initrode Global"}, headers=on(second["id"]))
    assert (await db.merchants.find_one({"_id": first["id"]}))["name"] == "Initech"
    assert (await db.merchants.find_one({"_id": second["id"]}))["name"] == "Initrode Global"
    camps = lambda mid: client.get("/merchant/campaigns", headers=on(mid))  # noqa: E731
    c2 = (await camps(second["id"])).json()
    assert c2 and {c["id"] for c in c2}.isdisjoint({c["id"] for c in (await camps(first["id"])).json()})

    # Someone already on a team can be invited to another program too.
    r = await client.post("/merchant/team/invites", json={"email": "multi@initech.example"}, headers=owner())
    assert r.status_code == 200, r.text
    token = re.search(r"/invite/(\w+)", (await db.emails.find_one({"to": "multi@initech.example", "kind": "team_invite"}))["text"]).group(1)
    assert (await client.post(f"/auth/invites/{token}/accept", headers=h)).status_code == 200
    assert len((await client.get("/auth/me", headers=h)).json()["merchants"]) == 3
    assert (await client.get("/merchant", headers=on(S["merchant_id"]))).json()["id"] == S["merchant_id"]

    for i in range(8):  # 10 created in all; joining a team doesn't count
        assert (await client.post("/merchant", json={"name": f"P{i}", "website": "https://p.example"}, headers=h)).status_code == 200
    assert (await client.post("/merchant", json={"name": "One too many", "website": "https://p.example"}, headers=h)).status_code == 409
