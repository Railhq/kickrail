"""PayPal Payouts API with the merchant's own REST app credentials.

One batch per Kickrail payout: sender_batch_id is the payout id, so PayPal itself
refuses a duplicate batch, and each item's sender_item_id is "<payout>:<affiliate>".
Item outcomes arrive asynchronously; the dispatcher polls processing batches.
"""

import httpx

from ..crypto import decrypt

BASES = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
# Item states that will not change again (UNCLAIMED becomes RETURNED after 30 days).
DONE_OK = {"SUCCESS"}
DONE_FAILED = {"FAILED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED", "DENIED"}


class PayPalError(Exception):
    pass


class PayPal:
    def __init__(self, client_id: str, secret: str, mode: str = "sandbox"):
        self.client_id, self.secret, self.base = client_id, secret, BASES[mode]

    @classmethod
    def for_merchant(cls, merchant: dict) -> "PayPal":
        p = merchant.get("paypal")
        if not p:
            raise PayPalError("connect PayPal first")
        return cls(p["client_id"], decrypt(p["secret_enc"]), p["mode"])

    async def _token(self, c: httpx.AsyncClient) -> str:
        r = await c.post(f"{self.base}/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=(self.client_id, self.secret))
        if r.status_code != 200:
            raise PayPalError(f"PayPal rejected the credentials ({r.status_code})")
        return r.json()["access_token"]

    async def verify(self) -> None:
        async with httpx.AsyncClient(timeout=20) as c:
            await self._token(c)

    async def create_batch(self, sender_batch_id: str, subject: str, items: list[dict]) -> str:
        """items: {email, amount_cents, currency, sender_item_id, note}"""
        body = {
            "sender_batch_header": {"sender_batch_id": sender_batch_id, "email_subject": subject, "recipient_type": "EMAIL"},
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "receiver": i["email"],
                    "amount": {"value": f"{i['amount_cents'] / 100:.2f}", "currency": i["currency"].upper()},
                    "sender_item_id": i["sender_item_id"],
                    "note": i["note"],
                }
                for i in items
            ],
        }
        async with httpx.AsyncClient(timeout=30) as c:
            token = await self._token(c)
            r = await c.post(f"{self.base}/v1/payments/payouts", json=body, headers={"authorization": f"Bearer {token}"})
        if r.status_code not in (200, 201):
            raise PayPalError(_error(r))
        return r.json()["batch_header"]["payout_batch_id"]

    async def batch(self, batch_id: str) -> dict:
        """{"status": batch_status, "items": [{"sender_item_id", "status", "item_id", "error"}]}"""
        items, page = [], 1
        async with httpx.AsyncClient(timeout=30) as c:
            token = await self._token(c)
            while True:
                r = await c.get(f"{self.base}/v1/payments/payouts/{batch_id}", params={"page": page, "page_size": 1000, "total_required": "true"}, headers={"authorization": f"Bearer {token}"})
                if r.status_code != 200:
                    raise PayPalError(_error(r))
                data = r.json()
                for i in data.get("items") or []:
                    items.append(
                        {
                            "sender_item_id": i["payout_item"]["sender_item_id"],
                            "status": i.get("transaction_status", "PENDING"),
                            "item_id": i.get("payout_item_id"),
                            "error": (i.get("errors") or {}).get("message"),
                        }
                    )
                if page >= (data.get("total_pages") or 1):
                    break
                page += 1
        return {"status": data["batch_header"]["batch_status"], "items": items}


def _error(r: httpx.Response) -> str:
    try:
        d = r.json()
        return d.get("message") or d.get("name") or r.text[:200]
    except ValueError:
        return f"PayPal error {r.status_code}"
