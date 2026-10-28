"""Importing a program from Rewardful, and the CSV exports."""

import asyncio
import csv
import io

import pytest

from app import deps
from app.main import app
from app.services.payouts import payable
from app.services.affiliates import pipeline
from app.services.rewardful_import import RewardfulError, RewardfulNotFound, backfill_links, backfill_visitors


def auth(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, db, email, name):
    r = await client.post("/auth/signup", json={"email": email, "password": "correct-horse", "name": name})
    await db.users.update_one({"email": email}, {"$set": {"email_verified": True}})
    return r.json()["token"]


CAMPAIGNS = [
    {"id": "c-main", "name": "Friends", "default": True, "reward_type": "percent", "commission_percent": 25.0, "max_commission_period_months": 12, "max_commissions": None,
     "days_until_commissions_are_due": 30, "minimum_payout_cents": 1000, "private": False, "url": "https://rwco.example/pricing", "created_at": "2025-01-02T00:00:00.000Z"},
    {"id": "c-vip", "name": "VIP", "default": False, "reward_type": "amount", "commission_amount_cents": 5000, "commission_amount_currency": "USD", "max_commissions": 1,
     "days_until_commissions_are_due": 0, "minimum_payout_cents": 0, "private": True, "url": "https://elsewhere.example/", "created_at": "2025-01-03T00:00:00.000Z"},
]


def affiliate(i, email, token, campaign="c-main", state="active", coupon=None, **kw):
    return {"id": f"a-{i}", "email": email, "first_name": f"Aff{i}", "last_name": "Doe", "state": state, "campaign": {"id": campaign},
            "links": [{"id": f"l-{i}", "token": token}], "coupon": coupon, "created_at": "2025-02-01T00:00:00.000Z", **kw}


AFFILIATES = [
    affiliate(1, "Ann@rw.example", "ann", coupon={"id": "cp-1", "token": "ANN20", "external_id": "promo_ann"}, paypal_email="ann.pay@rw.example", stripe_customer_id="cus_annself"),
    affiliate(2, "bob@rw.example", "Bob", campaign="c-vip"),
    affiliate(3, "cat@rw.example", "cat", state="disabled"),
    # Someone already in the Kickrail program keeps their account and gets the old link too.
    affiliate(4, "kept@rw.example", "keptold"),
]
for n in range(5, 130):  # more than one page
    AFFILIATES.append(affiliate(n, f"bulk{n}@rw.example", f"bulk{n}"))

REFERRALS = [
    {"id": "r-1", "affiliate": {"id": "a-1"}, "customer": {"id": "cus_fred", "email": "Fred@buyer.example"}, "stripe_customer_id": "cus_fred", "conversion_state": "conversion",
     "link": {"id": "l-1", "url": "https://rwco.example/?via=ann", "token": "ann"}, "created_at": "2025-03-01T00:00:00.000Z", "became_conversion_at": "2025-03-02T00:00:00.000Z"},
    {"id": "r-2", "affiliate": {"id": "a-2"}, "customer": {"email": "lead@buyer.example"}, "conversion_state": "lead", "created_at": "2025-03-05T00:00:00.000Z"},
    {"id": "r-3", "affiliate": {"id": "a-1"}, "customer": {"id": "cus_known", "email": "known@buyer.example"}, "stripe_customer_id": "cus_known", "conversion_state": "conversion"},
]


def commission(i, state, amount, aff="a-1", ref="r-1", due="2025-04-01T00:00:00.000Z", paid=None):
    return {"id": f"m-{i}", "amount": amount, "currency": "USD", "state": state, "due_at": due, "paid_at": paid, "created_at": "2025-03-02T00:00:00.000Z", "campaign": {"id": "c-main"},
            "sale": {"sale_amount_cents": amount * 4, "refund_amount_cents": 0, "stripe_charge_id": f"ch_{i}", "affiliate": {"id": aff}, "referral": {"id": ref}}}


COMMISSIONS = [
    commission(1, "paid", 2500, paid="2025-04-03T00:00:00.000Z"),
    commission(2, "due", 2500),
    commission(3, "pending", 2500, due="2099-01-01T00:00:00.000Z"),
    commission(4, "voided", 2500),
]
PAYOUTS = [
    {"id": "p-1-uuid-0000-1111", "state": "paid", "amount": 2500, "currency": "USD", "paid_at": "2025-04-03T00:00:00.000Z", "created_at": "2025-04-02T00:00:00.000Z",
     "affiliate": {"id": "a-1"}, "commissions": [{"id": "m-1"}]},
]


class FakeRewardful:
    calls: list[tuple[str, list]] = []
    secret: str | None = None

    def __init__(self, secret):
        FakeRewardful.secret = secret

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def get(self, path, params):
        if self.secret == "bad-secret-123":
            raise RewardfulError("Rewardful didn't accept that API secret")
        FakeRewardful.calls.append((path, params))
        if path.startswith("/affiliates/"):
            hit = next((a for a in AFFILIATES if a["id"] == path.split("/")[-1]), None)
            if not hit:
                raise RewardfulNotFound(f"Rewardful has nothing at {path}")
            return hit
        if path == "/affiliates":
            # Rewardful matches the email exactly, ignoring case.
            email = dict(params).get("email", "")
            return {"data": [a for a in AFFILIATES if a["email"].lower() == email.lower()], "pagination": {}}
        return {"data": [], "pagination": {}}

    async def pages(self, path, params=()):
        FakeRewardful.calls.append((path, list(params)))
        rows = {"/campaigns": CAMPAIGNS, "/affiliates": AFFILIATES, "/affiliate_coupons": [{"affiliate_id": "a-2", "token": "BOBX", "external_id": "promo_bobx"}],
                "/referrals": REFERRALS, "/commissions": COMMISSIONS, "/payouts": PAYOUTS}[path]
        if aff := dict(params).get("affiliate_id"):
            owner = {"/affiliate_coupons": lambda r: r["affiliate_id"], "/referrals": lambda r: r["affiliate"]["id"], "/commissions": lambda r: r["sale"]["affiliate"]["id"],
                     "/payouts": lambda r: r["affiliate"]["id"]}[path]
            rows = [r for r in rows if owner(r) == aff]
        if path == "/referrals" and ("expand[]", "affiliate") not in params:
            rows = [{k: v for k, v in r.items() if k != "affiliate"} for r in rows]  # as Rewardful does
        for i in range(0, len(rows), 100):
            yield rows[i:i + 100], len(rows)


@pytest.fixture(scope="module")
def rewardful():
    app.dependency_overrides[deps.rewardful_client] = lambda: FakeRewardful
    yield FakeRewardful
    app.dependency_overrides.pop(deps.rewardful_client, None)


async def wait(client, h):
    for _ in range(200):
        imp = (await client.get("/merchant/import", headers=h)).json()["import"]
        if imp["status"] != "running":
            return imp
        await asyncio.sleep(0.05)
    raise AssertionError("import never finished")


async def test_import_from_rewardful(client, db, rewardful):
    owner = await signup(client, db, "owner@rwco.example", "Rae")
    h = auth(owner)
    mid = (await client.post("/merchant", json={"name": "Rwco", "website": "https://rwco.example"}, headers=h)).json()["merchant"]["id"]
    await db.merchants.update_one({"_id": mid}, {"$set": {"plan": {"id": "free"}}})
    kept = await signup(client, db, "kept@rw.example", "Kept")
    kept_aff = (await client.post("/programs/rwco/join", json={}, headers=auth(kept))).json()
    # A customer Kickrail already tracked keeps the affiliate Kickrail gave them.
    await db.referrals.insert_one({"_id": "ref_known", "merchant_id": mid, "affiliate_id": kept_aff["id"], "campaign_id": "x", "status": "customer", "stripe_customer_id": "cus_known", "flags": []})

    r = await client.post("/merchant/import/rewardful", json={"api_secret": "bad-secret-123"}, headers=h)
    assert r.status_code == 400 and "API secret" in r.json()["detail"]
    r = await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1"}, headers=h)
    assert r.status_code == 200, r.text
    assert "sk_live_rewardful_1" not in r.text
    imp = await wait(client, h)
    assert imp["status"] == "done", imp
    assert imp["counts"]["affiliates"] == len(AFFILIATES) and imp["counts"]["campaigns"] == 1
    # The Free plan has one campaign, so VIP's affiliates land in the default one, with a warning.
    assert any("VIP" in w and "default campaign" in w for w in imp["warnings"])
    assert any("elsewhere.example" in w for w in imp["warnings"])
    stored = await db.imports.find_one({"_id": imp["id"]})
    assert "sk_live_rewardful_1" not in str(stored)

    default = await db.campaigns.find_one({"merchant_id": mid, "is_default": True})
    assert default["rewardful_id"] == "c-main" and default["rule"] == {"type": "percent", "bps": 2500}
    assert default["duration"] == {"mode": "months", "months": 12} and default["hold_days"] == 30 and default["min_payout_cents"] == 1000
    assert default["landing_url"] == "https://rwco.example/pricing"
    assert await db.campaigns.count_documents({"merchant_id": mid}) == 1

    ann = await db.affiliates.find_one({"merchant_id": mid, "rewardful_id": "a-1"})
    ann_user = await db.users.find_one({"_id": ann["user_id"]})
    assert ann["token"] == "ann" and ann["code"] == "ANN20" and ann["stripe_promotion_code_id"] == "promo_ann" and ann["status"] == "approved"
    assert ann["metadata"] == {"stripe_customer_id": "cus_annself"}
    assert ann_user["email"] == "ann@rw.example" and "password_hash" not in ann_user and "claim_token_hash" not in ann_user
    assert ann_user["payout_details"] == {"method": "paypal", "value": "ann.pay@rw.example"}
    bob = await db.affiliates.find_one({"merchant_id": mid, "rewardful_id": "a-2"})
    assert bob["token"] == "bob" and bob["campaign_id"] == default["_id"]
    assert (await db.affiliate_codes.find_one({"affiliate_id": bob["_id"]}))["stripe_promotion_code_id"] == "promo_bobx"
    assert (await db.affiliates.find_one({"merchant_id": mid, "rewardful_id": "a-3"}))["status"] == "rejected"
    kept_doc = await db.affiliates.find_one({"_id": kept_aff["id"]})
    assert kept_doc["rewardful_id"] == "a-4"
    assert await db.affiliate_links.find_one({"affiliate_id": kept_aff["id"], "token": "keptold"})
    # Old links resolve: ?via=bob works as before.
    click = await client.post("/track/click", content='{"key": "%s", "id": "kr_abcdef0123456789abcd", "token": "Bob"}' % (await db.merchants.find_one({"_id": mid}))["public_key"])
    assert click.status_code == 204 and await db.clicks.find_one({"merchant_id": mid, "affiliate_id": bob["_id"]})

    fred = await db.referrals.find_one({"merchant_id": mid, "rewardful_id": "r-1"})
    assert fred["stripe_customer_id"] == "cus_fred" and fred["email"] == "fred@buyer.example" and fred["status"] == "customer" and fred["first_paid_at"]
    assert fred["via"] == {"token": "ann", "url": "https://rwco.example/?via=ann"}
    assert "via" not in await db.referrals.find_one({"merchant_id": mid, "rewardful_id": "r-2"})
    assert (await db.referrals.find_one({"merchant_id": mid, "rewardful_id": "r-2"}))["status"] == "lead"
    assert await db.referrals.count_documents({"merchant_id": mid, "stripe_customer_id": "cus_known"}) == 1

    coms = {c["rewardful_id"]: c async for c in db.commissions.find({"merchant_id": mid})}
    assert {k: c["status"] for k, c in coms.items()} == {"m-1": "paid", "m-2": "pending", "m-3": "pending", "m-4": "void"}
    assert coms["m-1"]["payout_id"].startswith("rw") and coms["m-1"]["referral_id"] == fred["_id"] and coms["m-1"]["base_cents"] == 10000
    payout = await db.payouts.find_one({"_id": coms["m-1"]["payout_id"]})
    assert payout["status"] == "paid" and payout["total_cents"] == 2500 and payout["items"][0]["commission_ids"] == [coms["m-1"]["_id"]]
    # The due one is still owed and shows on the Payouts page; the future one isn't due yet.
    assert [l["amount_cents"] for l in await payable(db, mid)] == [2500]

    # Nothing was announced to the merchant's integrations, and no one was emailed.
    assert await db.events.count_documents({"merchant_id": mid, "type": {"$in": ["affiliate.created", "referral.created", "commission.created"]}}) == 1  # kept's own join
    assert await db.emails.count_documents({"merchant_id": mid, "kind": "welcome", "to": {"$regex": "rw.example$"}}) <= 1

    # Running it again updates instead of copying.
    counts = {c: await db[c].count_documents({"merchant_id": mid}) for c in ("affiliates", "referrals", "commissions", "payouts", "affiliate_links", "affiliate_codes")}
    before = await db.emails.count_documents({"merchant_id": mid})
    await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1"}, headers=h)
    assert (await wait(client, h))["status"] == "done"
    assert counts == {c: await db[c].count_documents({"merchant_id": mid}) for c in counts}
    assert await db.emails.count_documents({"merchant_id": mid}) == before

    # Claim emails, when asked for, go once to each approved affiliate without a password.
    await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1", "send_claim_emails": True}, headers=h)
    await wait(client, h)
    claims = await db.emails.find({"merchant_id": mid, "subject": {"$regex": "has moved"}}).to_list(None)
    assert len(claims) == len(AFFILIATES) - 2  # not the disabled one, not the one who already had a login
    assert {"ann@rw.example", "bob@rw.example"} <= {c["to"] for c in claims} and "claim?token=" in claims[0]["text"]
    assert "?via=ann" in next(c for c in claims if c["to"] == "ann@rw.example")["text"]
    await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1", "send_claim_emails": True}, headers=h)
    await wait(client, h)
    assert await db.emails.count_documents({"merchant_id": mid, "subject": {"$regex": "has moved"}}) == len(claims)


async def test_import_only_some_affiliates(client, db, rewardful):
    h = auth(await signup(client, db, "owner3@rwco.example", "Rio"))
    mid = (await client.post("/merchant", json={"name": "Picky", "website": "https://rwco.example"}, headers=h)).json()["merchant"]["id"]
    await db.merchants.update_one({"_id": mid}, {"$set": {"plan": {"id": "growth"}}})
    FakeRewardful.calls.clear()

    only = [" ANN@rw.example", "a-2", "nobody@rw.example", "a-404", "a-2"]
    r = await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1", "only": only}, headers=h)
    assert r.status_code == 200, r.text
    imp = await wait(client, h)
    assert imp["status"] == "done", imp
    assert imp["only"] == ["ann@rw.example", "a-2", "nobody@rw.example", "a-404"]
    assert any(w.startswith("nobody@rw.example:") for w in imp["warnings"]) and any(w.startswith("a-404:") for w in imp["warnings"])
    assert imp["counts"] == {"campaigns": 2, "affiliates": 2, "referrals": 3, "commissions": 4, "payouts": 1}

    # Only the two affiliates came over, with their own campaigns, codes and records.
    assert {a["rewardful_id"] async for a in db.affiliates.find({"merchant_id": mid})} == {"a-1", "a-2"}
    assert {c.get("rewardful_id") async for c in db.campaigns.find({"merchant_id": mid})} == {"c-main", "c-vip"}
    bob = await db.affiliates.find_one({"merchant_id": mid, "rewardful_id": "a-2"})
    assert (await db.affiliate_codes.find_one({"affiliate_id": bob["_id"]}))["code"] == "BOBX"
    assert await db.referrals.count_documents({"merchant_id": mid}) == 3 and await db.payouts.count_documents({"merchant_id": mid}) == 1
    # It never walked the whole program: every list call asked for one affiliate.
    lists = [(p, dict(q)) for p, q in FakeRewardful.calls if p in ("/affiliate_coupons", "/referrals", "/commissions", "/payouts")]
    assert lists and all(q.get("affiliate_id") in ("a-1", "a-2") for _, q in lists)
    assert not any(p == "/affiliates" and "email" not in dict(q) for p, q in FakeRewardful.calls)

    # Naming nobody real fails the run without importing anything.
    await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1", "only": ["nobody@rw.example"]}, headers=h)
    imp = await wait(client, h)
    assert imp["status"] == "failed" and "None of the affiliates" in imp["error"]
    r = await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1", "only": ["x"] * 101}, headers=h)
    assert r.status_code == 422


async def test_backfill_links_touches_only_the_link(client, db, rewardful):
    h = auth(await signup(client, db, "owner4@rwco.example", "Ren"))
    mid = (await client.post("/merchant", json={"name": "Older", "website": "https://rwco.example"}, headers=h)).json()["merchant"]["id"]
    await db.merchants.update_one({"_id": mid}, {"$set": {"plan": {"id": "growth"}}})
    await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1", "only": ["a-1", "a-2"]}, headers=h)
    assert (await wait(client, h))["status"] == "done"
    # As an import from before links were kept left it.
    await db.referrals.update_many({"merchant_id": mid}, {"$unset": {"via": ""}})
    before = {c: await db[c].find({"merchant_id": mid}).to_list(None) for c in ("referrals", "commissions", "payouts", "affiliates")}

    FakeRewardful.calls.clear()
    counts = await backfill_links(db, mid, FakeRewardful("sk_live_rewardful_1"))
    assert counts == {"affiliates": 2, "seen": 3, "updated": 1}
    assert {p for p, _ in FakeRewardful.calls} == {"/referrals"}
    after = {c: await db[c].find({"merchant_id": mid}).to_list(None) for c in before}
    for c in ("commissions", "payouts", "affiliates"):
        assert after[c] == before[c]
    fred = next(r for r in after["referrals"] if r["rewardful_id"] == "r-1")
    assert fred.pop("via") == {"token": "ann", "url": "https://rwco.example/?via=ann"}
    assert after["referrals"] == before["referrals"]
    # Running it again changes nothing.
    assert (await backfill_links(db, mid, FakeRewardful("sk_live_rewardful_1")))["updated"] == 0


async def test_backfill_visitors_gives_clicks_a_history(client, db, rewardful):
    from datetime import UTC, datetime, timedelta

    h = auth(await signup(client, db, "owner5@rwco.example", "Vic"))
    mid = (await client.post("/merchant", json={"name": "Visits", "website": "https://rwco.example"}, headers=h)).json()["merchant"]["id"]
    await db.merchants.update_one({"_id": mid}, {"$set": {"plan": {"id": "growth"}}})
    await client.post("/merchant/import/rewardful", json={"api_secret": "sk_live_rewardful_1", "only": ["a-1", "a-2"]}, headers=h)
    assert (await wait(client, h))["status"] == "done"
    ann = await db.affiliates.find_one({"merchant_id": mid, "rewardful_id": "a-1"})
    # Both trackers ran for a while: Kickrail's clicks from then are already in Rewardful's total.
    before = datetime.now(UTC) - timedelta(days=3)
    await db.clicks.insert_many([{"_id": f"clk_v{i}", "merchant_id": mid, "affiliate_id": ann["_id"], "test": False, "created_at": before} for i in range(5)])
    p = await pipeline(db, ann)
    assert p["clicks"] == 5 and p["customers"] == 2 and p["customers_from_clicks"] == 0

    # One added over the API keeps the Rewardful id in metadata.
    api_aff = {k: v for k, v in ann.items() if k not in ("rewardful_id", "code")}
    await db.affiliates.insert_one({**api_aff, "_id": "aff_viaapi", "user_id": "usr_viaapi", "token": "viaapi", "metadata": {"rewardful_id": "a-7"}})
    AFFILIATES[0]["visitors"], AFFILIATES[1]["visitors"], AFFILIATES[6]["visitors"], AFFILIATES[7]["visitors"] = 40, 0, 9, 3
    try:
        counts = await backfill_visitors(db, mid, FakeRewardful("sk_live_rewardful_1"))
        assert counts == {"seen": len(AFFILIATES), "updated": 2, "no_visitors": len(AFFILIATES) - 3, "not_in_kickrail": 1}
        assert (await db.affiliates.find_one({"_id": "aff_viaapi"}))["imported_clicks"] == 9
        # Already set: a second run leaves it, --force refreshes it.
        assert (await backfill_visitors(db, mid, FakeRewardful("sk_live_rewardful_1")))["updated"] == 0
    finally:
        for i in (0, 1, 6, 7):
            AFFILIATES[i].pop("visitors")
    await db.clicks.insert_one({"_id": "clk_vnew", "merchant_id": mid, "affiliate_id": ann["_id"], "test": False, "created_at": datetime.now(UTC) + timedelta(seconds=1)})

    ann = await db.affiliates.find_one({"_id": ann["_id"]})
    p = await pipeline(db, ann)
    assert p["clicks"] == 41 and p["clicks_30d"] == 6 and p["customers_from_clicks"] == 2
    # The affiliate sees whom each commission was for, masked; the merchant gets the referral.
    seen = {c["customer"]["email"] for c in p["commissions"] if c["customer"]}
    assert seen <= {"fr***@buyer.example", "kn***@buyer.example"} and seen
    view = (await client.get(f"/merchant/affiliates/{ann['_id']}/view", headers=h)).json()
    c = next(c for c in view["commissions"] if c["customer"])
    assert c["customer"]["referral_id"].startswith("ref_") and "***" not in c["customer"]["email"]
    assert view["clicks"] == 41

    o = (await client.get("/merchant/overview", headers=h)).json()
    assert o["clicks"] == 41 + 9
    bob_refs = await db.referrals.count_documents({"merchant_id": mid, "affiliate_id": {"$ne": ann["_id"]}})
    assert o["imported_leads"] == bob_refs and o["leads_from_clicks"] == o["leads"] - bob_refs
    rows = (await client.get("/merchant/affiliates", headers=h)).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    assert next(r for r in rows if r["id"] == ann["_id"])["clicks"] == 41


async def test_exports(client, db, rewardful):
    h = auth(await signup(client, db, "owner2@rwco.example", "Ray"))
    await client.post("/merchant", json={"name": "Exportco", "website": "https://exportco.example"}, headers=h)
    aff_h = auth(await signup(client, db, "=cmd@exp.example", "=HYPERLINK(1)"))
    await client.post("/programs/exportco/join", json={}, headers=aff_h)
    r = await client.get("/merchant/export/affiliates.csv", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["id", "name", "email", "status"] and len(rows) == 2
    assert rows[1][1] == "'=HYPERLINK(1)"  # spreadsheets won't run it
    for kind in ("referrals", "commissions"):
        r = await client.get(f"/merchant/export/{kind}.csv", headers=h)
        assert r.status_code == 200 and len(list(csv.reader(io.StringIO(r.text)))) == 1
    assert (await client.get("/merchant/export/users.csv", headers=h)).status_code == 404


async def test_rewardful_client(monkeypatch):
    import base64

    import httpx

    from app.services import rewardful_import as ri

    real_sleep, slept = asyncio.sleep, []

    async def no_wait(s):
        slept.append(s)
        await real_sleep(0)

    monkeypatch.setattr(ri.asyncio, "sleep", no_wait)
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.headers["authorization"] != "Basic " + base64.b64encode(b"good-secret-1:").decode():
            return httpx.Response(401)
        page = int(req.url.params["page"])
        if page == 2 and sum(1 for r in seen if r.url.params.get("page") == "2") == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, json={"data": [{"id": f"x{page}"}], "pagination": {"next_page": page + 1 if page < 3 else None, "total_count": 3}})

    t = httpx.MockTransport(handler)
    async with ri.Rewardful("good-secret-1", transport=t) as api:
        rows = [r async for batch, _ in api.pages("/affiliates", [("expand[]", "links")]) for r in batch]
    assert [r["id"] for r in rows] == ["x1", "x2", "x3"] and slept == [1.0]  # waited out the 429
    assert seen[0].url.params.get_list("expand[]") == ["links"] and seen[0].url.params["limit"] == "100"
    with pytest.raises(RewardfulError, match="API secret"):
        async with ri.Rewardful("wrong-secret", transport=t) as api:
            await api.get("/campaigns", [("limit", 1)])
