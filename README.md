<p align="center"><img src="web/src/app/icon.svg" width="72" alt="Kickrail"></p>

<h1 align="center">Kickrail</h1>

<p align="center">Open-source affiliate and referral tracking for SaaS products that bill through Stripe.<br><a href="https://kickrail.com">kickrail.com</a> · <a href="https://kickrail.com/docs">Docs</a> · <a href="https://kickrail.com/docs/switching">Switch from Rewardful</a> · <a href="https://kickrail.com/docs/mcp">Set up with an AI agent</a></p>

Affiliate and referral tracking for SaaS products that bill through Stripe. It is multi-tenant: any number of merchants can run programs, and affiliates use one login across all of them.

```
browser ──► web/ (Next.js) ──► backend/ (FastAPI) ──► MongoDB
             UI + /api/* proxy    all business logic      Stripe
```

- **`backend/`** holds all logic and data: auth, tracking, attribution, commissions, Stripe webhooks, payouts. It refuses every request without `X-Internal-Token` (except `/health`), so it is never exposed directly.
- **`web/`** is UI plus a server-side proxy. Pages and server actions call the backend from the Next.js server. `web/src/app/api/[...path]/route.ts` forwards public traffic (tracking script, beacons, Stripe webhooks with raw bodies, the merchant server API). The session lives in an httpOnly cookie and becomes a bearer token in the proxy.

## Run locally

Requires Python 3.13, Node 20+ and a local MongoDB.

```sh
make setup        # venv, npm install, example env files
# backend/.env: set KR_APP_SECRET and KR_INTERNAL_TOKEN (any long random strings)
# web/.env.local: INTERNAL_TOKEN = same value as KR_INTERNAL_TOKEN
make backend      # :8000
make web          # :3000
make test         # backend tests against a throwaway Mongo database
```

Backend settings use the `KR_` prefix (`KR_MONGODB_URI`, `KR_PUBLIC_URL`, …). This is deliberate: unprefixed names like `MONGODB_URI` are often already exported in a shell for other projects. `KR_PUBLIC_URL` must be the web app's public origin, because the backend uses it to build the script URL, the Stripe webhook URL and the Connect return URLs.

Stripe payouts need a Kickrail platform account with Connect enabled: `KR_PLATFORM_STRIPE_SECRET_KEY`, plus a platform webhook (`checkout.session.completed`, `account.updated`) pointing at `{KR_PUBLIC_URL}/api/webhooks/platform` with its secret in `KR_PLATFORM_STRIPE_WEBHOOK_SECRET`. Without it, everything except Stripe payouts still works, and manual payouts with CSV export are available.

## Merchant integration

1. **Connect Stripe.** In Settings, paste a restricted key. Kickrail stores it encrypted and creates its own webhook endpoint on the merchant's account.
2. **Add the script** to the marketing site and app:
   ```html
   <script async src="https://kickrail.com/api/kr.js?k=pk_kr_…"></script>
   ```
   It records `?via=` clicks and stores `kr_ref` in a first-party cookie on the widest domain plus localStorage. It also tags `buy.stripe.com` links, pricing tables and buy buttons with `client_reference_id`, adds a hidden `kickrail_referral` field to `<form data-kickrail>`, and exposes `window.Kickrail`.
3. **Report signups from the server** (the reliable path):
   ```http
   POST /api/v1/referrals
   Authorization: Bearer sk_kr_…
   {"referral": "<kr_ref cookie>", "email": "...", "user_id": "...", "stripe_customer_id": "...", "ip": "..."}
   ```
   You can also send `client_reference_id`, or `metadata.kr_ref` on the Stripe customer. Creator codes need no integration because they are real Stripe promotion codes.
4. **Optional first-party mode.** Proxy `/kr/*` on your own domain to `https://kickrail.com/api/*` and load `/kr/kr.js?k=…&api=/kr`.

## How money flows

- **Earning.** `invoice.paid` (tax excluded) and paid one-off Checkout sessions earn by the affiliate's campaign: a percent or flat amount, paid once, for N months, or forever. Commissions are idempotent per invoice or session.
- **Refunds and disputes.** These reduce or void unpaid commissions in proportion to the amount refunded. If the commission was already paid, a negative clawback line is netted from the affiliate's next payout.
- **Self-referral.** Matching email, company domain or sign-in IP flags the referral and holds its commissions until the merchant approves it.
- **Payouts.** A payout covers commissions past their hold period, for affiliates over the minimum. With Stripe, the merchant pays one Checkout on the platform account, then each affiliate gets a Connect transfer (`source_transaction`, idempotent). With manual payouts, the merchant marks the batch paid and downloads a CSV.

## Not yet verified against real Stripe

The tests use fake Stripe clients and signed webhooks. Before going live, run through Stripe test mode end to end and confirm:

- that the restricted-key permission list in Settings is sufficient
- invoice-to-payment-intent lookup through `invoice_payments`
- Connect Express onboarding, and cross-border transfer eligibility for affiliate countries (for example, India is not supported for cross-border payouts, so those affiliates need manual payouts)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributors sign a short [CLA](CLA.md) once, by commenting on their first pull request.

## License

[AGPL-3.0](LICENSE). You can use, modify and self-host Kickrail. If you run a modified version as a service for others, you must publish your changes under the same license. The hosted version is at [kickrail.com](https://kickrail.com).
