from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # KR_ prefix: generic names like MONGODB_URI are often already exported in the shell
    # (pointing at some other database), and must never leak in here.
    model_config = SettingsConfigDict(env_prefix="KR_", env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    mongodb_db: str = "kickrail"
    # Public base URL of the web app. Tracking snippet, webhook URLs and Connect
    # return URLs all point here; the web app proxies /api/* to this service.
    public_url: str = "http://localhost:3000"
    # 32+ random chars. Signs session tokens and encrypts merchant Stripe keys at rest.
    app_secret: str
    # Shared secret the web proxy sends so only it can reach this service.
    internal_token: str
    # Kickrail's own Stripe account: Connect platform for affiliate payouts.
    platform_stripe_secret_key: str = ""
    platform_stripe_webhook_secret: str = ""
    # Kickrail charging programs for their plan. Falls back to the platform key; set it
    # alone (e.g. a billing-only restricted key) to bill without turning on Connect payouts.
    billing_stripe_secret_key: str = ""
    billing_stripe_webhook_secret: str = ""
    # Secret of the Connect endpoint (account.updated for affiliate accounts), if separate.
    platform_stripe_connect_webhook_secret: str = ""
    # One-click "Connect with Stripe" for merchants (Connect OAuth, Standard accounts).
    # The client id (ca_...) comes from the platform's Connect settings; the secret key
    # must belong to that same platform account and falls back to the platform key.
    # Events from connected merchants arrive at /webhooks/platform through a Connect
    # endpoint (platform_stripe_connect_webhook_secret).
    stripe_oauth_client_id: str = ""
    stripe_oauth_secret_key: str = ""
    # Local dev only: Stripe won't register a webhook endpoint at a localhost URL, so
    # connecting a merchant skips that and trusts this secret instead. Use the one
    # `stripe listen --forward-to localhost:3100/api/webhooks/stripe/<merchant_id>` prints.
    dev_webhook_secret: str = ""
    # Fee added on top of a funded payout batch, in basis points (0 for own use).
    payout_fee_bps: int = 0
    # Outgoing mail. With no SMTP host, emails are kept in the outbox as "logged"
    # (visible in the dashboard) instead of being sent: right for local dev.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    mail_from: str = "Kickrail <no-reply@kickrail.com>"
    # Brevo transactional API key. When set it is used instead of SMTP.
    brevo_api_key: str = ""
    # Appended to the program name in From ("Codemia via Kickrail"). Empty when
    # mail goes out from the merchant's own domain.
    mail_via: str = " via Kickrail"
    # Recipients on these domains are never sent to, only logged (test data).
    mail_skip_domains: str = "example.com,example.org,example.net"
    # Custom portal domains point a CNAME here (e.g. portals.kickrail.com).
    portal_cname_target: str = "portals.kickrail.com"
    # Background delivery of webhooks, emails and PayPal status checks. Off in tests.
    dispatcher: bool = True
    # Railhq accounts (app/railhq.py, routers/railhq.py): one sign-in for the people who run
    # programs, the Railhq Pass and the MCP gateway. Any of the three empty: Kickrail keeps
    # its own operator logins. Affiliates (partners) never use Railhq.
    railhq_issuer: str = ""
    railhq_client_id: str = ""
    railhq_client_secret: str = ""

    @property
    def railhq_enabled(self) -> bool:
        return bool(self.railhq_issuer and self.railhq_client_id and self.railhq_client_secret)

    @property
    def mail_enabled(self) -> bool:
        return bool(self.brevo_api_key or self.smtp_host)

    @property
    def billing_key(self) -> str:
        return self.billing_stripe_secret_key or self.platform_stripe_secret_key

    @property
    def oauth_key(self) -> str:
        return self.stripe_oauth_secret_key or self.platform_stripe_secret_key

    @property
    def stripe_oauth(self) -> bool:
        return bool(self.stripe_oauth_client_id and self.oauth_key)

    @property
    def stripe_payouts(self) -> bool:
        """Stripe Connect payouts need Kickrail's own platform account."""
        return bool(self.platform_stripe_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
