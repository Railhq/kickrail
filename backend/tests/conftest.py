import hashlib
import hmac
import json
import os
import secrets
import time

os.environ.update(
    KR_MONGODB_URI=os.environ.get("KR_TEST_MONGODB_URI", "mongodb://127.0.0.1:27017"),
    KR_MONGODB_DB=f"kickrail_test_{secrets.token_hex(4)}",
    KR_APP_SECRET="test-secret-" + "x" * 40,
    KR_INTERNAL_TOKEN="internal-test",
    KR_PUBLIC_URL="https://kickrail.test",
    KR_PLATFORM_STRIPE_WEBHOOK_SECRET="whsec_platform",
    KR_PLATFORM_STRIPE_SECRET_KEY="",
    KR_DEV_WEBHOOK_SECRET="",
    KR_DISPATCHER="false",
    # Never inherit the real mail setup from .env.
    KR_BREVO_API_KEY="",
    KR_SMTP_HOST="",
    KR_MAIL_FROM="Kickrail <noreply@kickrail.test>",
    KR_MAIL_VIA=" via Kickrail",
)

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import deps  # noqa: E402
from app.db import close_db, get_db  # noqa: E402
from app.main import app  # noqa: E402


class FakeMerchantStripe:
    """Stands in for a merchant's Stripe account."""

    def __init__(self):
        self.promotion_codes: list[tuple[str, str]] = []
        self.active_codes: dict[str, str] = {}
        self.invoice_pi: dict[str, str] = {}
        self.session_pi: dict[str, str] = {}
        self.payment_intents: list[dict] = []
        self.webhook_updates: list[str] = []
        self.webhooks_deleted: list[str] = []
        self.customer_times: dict = {}
        self.customer_metadata: dict[str, dict] = {}
        self.fail_customers: dict[str, Exception] = {}
        self.invoices: dict[str, dict] = {}

    async def account(self):
        # Each restricted key is its own Stripe account, as for real merchants.
        key = getattr(self, "key", None) or "acct_merchant"
        return {"id": key if key.startswith("acct_") else f"acct_{key}", "name": "Acme"}

    async def create_webhook(self, url):
        self.webhook_url = url
        return "we_1", "whsec_merchant"

    async def delete_webhook(self, endpoint_id):
        self.webhooks_deleted.append(endpoint_id)

    async def update_customer_metadata(self, customer_id, metadata):
        if customer_id in self.fail_customers:
            raise self.fail_customers[customer_id]
        self.customer_metadata[customer_id] = {**self.customer_metadata.get(customer_id, {}), **metadata}

    async def customer_created(self, customer_id):
        return self.customer_times.get(customer_id)

    async def payment_intent_for_invoice(self, invoice_id):
        return self.invoice_pi.get(invoice_id)

    async def invoice_for_payment_intent(self, pi):
        return next((i for i, p in self.invoice_pi.items() if p == pi), None)

    async def checkout_session_for_payment_intent(self, pi):
        return next((cs for cs, p in self.session_pi.items() if p == pi), None)

    async def succeeded_payment_intents(self, since):
        for pi in self.payment_intents:
            yield pi

    async def update_webhook_events(self, endpoint_id):
        self.webhook_updates.append(endpoint_id)

    async def invoice(self, invoice_id):
        return self.invoices[invoice_id]

    async def create_promotion_code(self, coupon_id, code, affiliate_id):
        # Like Stripe: one active promotion code per code string.
        if code in self.active_codes.values():
            raise RuntimeError(f"an active promotion code {code} already exists")
        self.promotion_codes.append((coupon_id, code))
        same = sum(1 for _, c in self.promotion_codes if c == code)
        pc_id = f"promo_{code}" if same == 1 else f"promo_{code}_{same}"
        self.active_codes[pc_id] = code
        return pc_id

    async def deactivate_promotion_code(self, promotion_code_id):
        self.active_codes.pop(promotion_code_id, None)

    async def list_coupons(self):
        return [{"id": "coupon_20", "name": "20% off", "percent_off": 20, "amount_off": None, "currency": None}]


class FakePlatform:
    def __init__(self):
        self.transfers: list[dict] = []
        self.enabled: set[str] = set()
        self.fail_for: set[str] = set()
        self.n = 0

    async def create_express_account(self, email, user_id, country):
        self.n += 1
        return f"acct_aff{self.n}"

    async def onboarding_link(self, account_id, refresh_url, return_url):
        return f"https://connect.stripe.test/{account_id}"

    async def dashboard_link(self, account_id):
        return f"https://dashboard.stripe.test/{account_id}"

    async def payout_status(self, account_id):
        return "ready" if account_id in self.enabled else "needs_info"

    async def funding_checkout(self, payout_id, amount_cents, currency, description, success_url, cancel_url):
        self.funding = (payout_id, amount_cents, currency)
        return f"cs_fund_{payout_id}", "https://checkout.stripe.test/fund"

    async def charge_for_session(self, session_id):
        return "ch_funding"

    async def transfer(self, amount_cents, currency, destination, source_charge, group, idempotency_key):
        if destination in self.fail_for:
            raise RuntimeError("account restricted")
        self.transfers.append({"amount": amount_cents, "currency": currency, "destination": destination, "source": source_charge, "key": idempotency_key})
        return f"tr_{len(self.transfers)}"


@pytest.fixture(scope="session")
def fakes():
    return {"merchant": FakeMerchantStripe(), "platform": FakePlatform()}


@pytest.fixture(scope="session", autouse=True)
async def setup_app(fakes):
    app.dependency_overrides[deps.merchant_api_factory] = lambda: (lambda m: fakes["merchant"])
    def key_client(key):
        fakes["merchant"].key = key
        return fakes["merchant"]
    app.dependency_overrides[deps.merchant_key_client] = lambda: key_client
    app.dependency_overrides[deps.platform_api] = lambda: fakes["platform"]
    # merchant.create_payout calls platform_api() directly (not as a dependency)
    import app.routers.merchant as mr

    mr.platform_api = lambda: fakes["platform"]
    import app.routers.webhooks as wh

    wh.platform_api = lambda: fakes["platform"]
    from app.services import fx

    async def fake_rates():
        return {"date": "2026-10-21", "rates": {"eur": 1.0, "usd": 1.1234, "inr": 106.13, "cad": 1.578}}

    fx.fetch = fake_rates
    db = await get_db()
    yield
    await db.client.drop_database(db.name)
    await close_db()


@pytest.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://backend", headers={"x-internal-token": "internal-test"}) as c:
        yield c


@pytest.fixture(scope="session")
async def db():
    return await get_db()


def sign(payload: str, secret: str) -> str:
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


async def send_event(client, url: str, secret: str, type_: str, obj: dict, event_id: str | None = None):
    event = {"id": event_id or f"evt_{secrets.token_hex(6)}", "type": type_, "data": {"object": obj}}
    payload = json.dumps(event)
    return await client.post(url, content=payload, headers={"stripe-signature": sign(payload, secret), "content-type": "application/json"})
