"""Self-referral signals. Flags for the merchant to review, never automatic
rejections: a coworker on the same office network is legitimate often enough."""

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com",
    "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "yandex.com", "qq.com",
    "163.com", "zoho.com",
}


def canonical_email(email: str) -> str:
    """mark+1@gmail.com and m.ark@gmail.com are the same inbox."""
    local, _, domain = email.strip().lower().partition("@")
    if domain == "googlemail.com":
        domain = "gmail.com"
    local = local.split("+")[0]
    if domain == "gmail.com":
        local = local.replace(".", "")
    return f"{local}@{domain}"


def self_referral_flags(affiliate_email: str, affiliate_ip_hashes: list[str], customer_email: str | None, customer_ip_hash: str | None) -> list[dict]:
    flags = []
    if customer_email:
        a, c = canonical_email(affiliate_email), canonical_email(customer_email)
        if a == c:
            flags.append({"kind": "self_email", "detail": "customer email matches the affiliate's account email"})
        else:
            domain = a.split("@")[1]
            if domain and domain == c.split("@")[1] and domain not in FREE_MAIL:
                flags.append({"kind": "self_domain", "detail": f"customer and affiliate share the {domain} domain"})
    if customer_ip_hash and customer_ip_hash in (affiliate_ip_hashes or []):
        flags.append({"kind": "self_ip", "detail": "customer signed up from an IP the affiliate has logged in from"})
    return flags
