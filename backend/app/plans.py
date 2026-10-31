"""Kickrail's own pricing. Every program (merchant) has a plan; limits are per program.

Nothing here ever stops tracking: over the revenue cap a program keeps working and
gets a notice, and on a downgrade what already exists (extra domains, teammates,
campaigns) keeps running. Gates only refuse adding more.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

TRIAL_DAYS = 14
UNLIMITED = 10**9

PLANS: dict[str, dict] = {
    "free": {
        "name": "Free", "month": 0, "year": 0, "revenue_cap": 1_000,
        "domains": 0, "campaigns": 1, "teammates": 1, "creator_codes": False, "api": False, "stripe_payouts": False, "branding": True, "priority_support": False,
    },
    "starter": {
        "name": "Starter", "month": 29, "year": 290, "revenue_cap": 10_000,
        "domains": 1, "campaigns": UNLIMITED, "teammates": 3, "creator_codes": True, "api": False, "stripe_payouts": False, "branding": True, "priority_support": False,
    },
    "growth": {
        "name": "Growth", "month": 79, "year": 790, "revenue_cap": 50_000,
        "domains": 3, "campaigns": UNLIMITED, "teammates": UNLIMITED, "creator_codes": True, "api": True, "stripe_payouts": True, "branding": False, "priority_support": False,
    },
    "scale": {
        "name": "Scale", "month": 149, "year": 1_490, "revenue_cap": 150_000,
        "domains": 10, "campaigns": UNLIMITED, "teammates": UNLIMITED, "creator_codes": True, "api": True, "stripe_payouts": True, "branding": False, "priority_support": True,
    },
}
PAID = ["starter", "growth", "scale"]
ORDER = ["free", *PAID]
# What the owner's Railhq Pass gives a program it covers (merchants.railhq_pass, kept by
# services/pass_coverage.py) on the free plan. A Pass covers 1, 3 or 10 programs by tier.
PASS_PLAN = PAID[0]

# What a gate's 402 says, and the cheapest plan that has it.
FEATURES = {
    "domains": "More portal domains",
    "campaigns": "More than one campaign",
    "teammates": "More teammates",
    "creator_codes": "Creator codes",
    "api": "API access to affiliates, commissions and payouts",
    "webhooks": "Webhooks",
    "stripe_payouts": "Stripe Connect payouts",
}
_FEATURE_KEY = {"webhooks": "api"}


def new_trial(now: datetime | None = None) -> dict:
    """New programs try Growth for 14 days, no card."""
    now = now or datetime.now(UTC)
    return {"id": "growth", "status": "trialing", "trial_ends_at": now + timedelta(days=TRIAL_DAYS)}


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=UTC) if d and d.tzinfo is None else d


def current(m: dict, now: datetime | None = None) -> dict:
    """The plan in force right now, with its limits, whatever is stored."""
    now = now or datetime.now(UTC)
    if m.get("comped"):
        return {**PLANS["scale"], "id": "scale", "status": "comped", "comped": True, "revenue_cap": None}
    p = m.get("plan") or {}
    pid, status = p.get("id", "free"), p.get("status", "active")
    trial_ends = _aware(p.get("trial_ends_at"))
    if pid not in PLANS or status in ("canceled", "incomplete", "incomplete_expired", "unpaid"):
        pid = "free"
    elif status == "trialing" and not p.get("stripe_subscription") and (not trial_ends or trial_ends <= now):
        pid, status = "free", "trial_ended"
    if pid == "free" and m.get("railhq_pass"):
        # Covered by the owner's Railhq Pass: Starter. A paid or trial plan above it wins.
        return {**PLANS[PASS_PLAN], "id": PASS_PLAN, "status": "active", "source": "pass", "comped": False, "trial_ends_at": None, "interval": None,
                "current_period_end": None, "cancel_at_period_end": False, "subscribed": False}
    return {
        **PLANS[pid],
        "id": pid,
        "status": status if pid != "free" or status == "trial_ended" else "active",
        "comped": False,
        "trial_ends_at": trial_ends if p.get("status") == "trialing" else None,
        "interval": p.get("interval"),
        "current_period_end": p.get("current_period_end"),
        "cancel_at_period_end": bool(p.get("cancel_at_period_end")),
        "subscribed": bool(p.get("stripe_subscription")) and p.get("status") not in ("canceled", "incomplete_expired"),
    }


def cheapest_with(feature: str, need: int = 1) -> str:
    key = _FEATURE_KEY.get(feature, feature)
    for pid in ORDER:
        v = PLANS[pid][key]
        if (v is True) or (not isinstance(v, bool) and v >= need):
            return PLANS[pid]["name"]
    return PLANS["scale"]["name"]


def require(m: dict, feature: str) -> None:
    """402 unless the program's plan has this feature."""
    if not current(m)[_FEATURE_KEY.get(feature, feature)]:
        raise HTTPException(402, f"{FEATURES[feature]} need the {cheapest_with(feature)} plan or higher. Upgrade in Billing.")


def require_room(m: dict, feature: str, used: int) -> None:
    """402 when adding one more would go past the plan's count limit."""
    limit = current(m)[feature]
    if used + 1 > limit:
        raise HTTPException(402, f"Your plan includes {limit}. {FEATURES[feature]} need the {cheapest_with(feature, used + 1)} plan or higher. Upgrade in Billing.")
