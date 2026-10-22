"""Commission rules. Pure functions; no I/O.

A campaign document carries:
  rule:     {"type": "percent", "bps": 3000} | {"type": "flat", "cents": 1000, "currency": "usd"}
  duration: {"mode": "once"} | {"mode": "months", "months": 12} | {"mode": "forever"}
  hold_days: days a commission waits before it becomes payable (refund window)
  product_rules: [{"match": "product" | "price", "id": "prod_...", "rule": <rule> | {"type": "none"}}]
  lead_bounty: {"cents": 500, "currency": "usd"} | None, paid once per referred signup
  reward: {"type": "custom", ...} | None, rewards that aren't cash instead (services/rewards.py)

An affiliate can carry rate_override (a rule) that replaces the campaign's default
rule for them. Product rules still win for the products they name, because they
usually exist to exclude or cap something (a hardware add-on, a low-margin plan).
"""

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Decision:
    ok: bool
    amount_cents: int = 0
    currency: str = ""
    due_at: datetime | None = None
    reason: str = ""


def add_months(d: datetime, months: int) -> datetime:
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


@dataclass
class Line:
    """One invoice or checkout line: what the customer paid for it, pre-tax."""

    amount_cents: int
    product_id: str | None = None
    price_id: str | None = None


def effective_rule(campaign: dict, affiliate: dict | None) -> dict:
    return (affiliate or {}).get("rate_override") or campaign["rule"]


def rule_for_line(campaign: dict, default_rule: dict, line: Line) -> dict:
    rules = campaign.get("product_rules") or []
    for match, value in (("price", line.price_id), ("product", line.product_id)):
        if value:
            for r in rules:
                if r["match"] == match and r["id"] == value:
                    return r["rule"]
    return default_rule


def _amount(rule: dict, base_cents: int, currency: str) -> tuple[int, str]:
    if rule["type"] == "percent":
        return round(base_cents * rule["bps"] / 10_000), currency
    if rule["type"] == "flat":
        return rule["cents"], rule["currency"]
    return 0, currency


def decide_commission(
    campaign: dict, base_cents: int, currency: str, paid_at: datetime, first_paid_at: datetime, prior_commissions: int,
    affiliate: dict | None = None, lines: list[Line] | None = None,
) -> Decision:
    if base_cents <= 0:
        return Decision(False, reason="nothing paid")

    duration = campaign["duration"]
    if duration["mode"] == "once" and prior_commissions > 0:
        return Decision(False, reason="one-time commission already earned")
    if duration["mode"] == "months" and paid_at >= add_months(first_paid_at, duration["months"]):
        return Decision(False, reason=f"outside the {duration['months']}-month commission window")

    rule = effective_rule(campaign, affiliate)
    paid_lines = [l for l in lines or [] if l.amount_cents > 0]
    if campaign.get("product_rules") and paid_lines:
        amount, out_currency = _by_line(campaign, rule, base_cents, currency.lower(), paid_lines)
    else:
        amount, out_currency = _amount(rule, base_cents, currency)
    if amount <= 0:
        return Decision(False, reason="no commission for these products" if rule["type"] == "none" or paid_lines else "commission rounds to zero")
    return Decision(True, amount, out_currency.lower(), paid_at + timedelta(days=campaign["hold_days"]))


def _by_line(campaign: dict, default_rule: dict, base_cents: int, currency: str, lines: list[Line]) -> tuple[int, str]:
    """Split what was actually paid (after discounts, before tax) across lines in
    proportion to their list amounts, then apply each line's rule. A flat rule pays
    once per line; one in another currency than the payment pays nothing, since a
    commission has a single currency."""
    gross = sum(l.amount_cents for l in lines)
    total, given = 0, 0
    for i, line in enumerate(lines):
        share = base_cents - given if i == len(lines) - 1 else round(base_cents * line.amount_cents / gross)
        given += share
        amount, cur = _amount(rule_for_line(campaign, default_rule, line), share, currency)
        if cur.lower() == currency:
            total += amount
    return total, currency


@dataclass
class RefundAction:
    kind: str  # "none" | "reduce" | "void" | "clawback"
    amount_cents: int = 0  # new amount for "reduce", negative amount for "clawback"


def decide_refund(status: str, original_cents: int, current_cents: int, refunded_cents: int, charge_cents: int) -> RefundAction:
    """refunded_cents is the newly refunded (or disputed) amount, not the running total.
    The cut is proportional to the original commission so repeated partial refunds add
    up exactly. Unpaid commissions shrink in place; paid ones get a negative clawback
    that nets against the affiliate's next payout."""
    if status == "void" or refunded_cents <= 0 or charge_cents <= 0:
        return RefundAction("none")
    cut = min(round(original_cents * min(1.0, refunded_cents / charge_cents)), current_cents if status != "paid" else original_cents)
    if cut <= 0:
        return RefundAction("none")
    if status == "paid":
        return RefundAction("clawback", -cut)
    remaining = current_cents - cut
    return RefundAction("void") if remaining <= 0 else RefundAction("reduce", remaining)


@dataclass
class PayableLine:
    affiliate_id: str
    currency: str
    amount_cents: int = 0
    commission_ids: list[str] = field(default_factory=list)


def payable_lines(commissions: list[dict], now: datetime, min_payout_cents) -> list[PayableLine]:
    """Pending commissions past their hold, summed per affiliate and currency.
    Clawbacks are pending negatives, so they net out here."""
    lines: dict[tuple[str, str], PayableLine] = {}
    for c in commissions:
        if c["status"] != "pending" or c["due_at"] > now or c.get("held"):
            continue
        key = (c["affiliate_id"], c["currency"])
        line = lines.setdefault(key, PayableLine(*key))
        line.amount_cents += c["amount_cents"]
        line.commission_ids.append(c["_id"])
    return [l for l in lines.values() if l.amount_cents > 0 and l.amount_cents >= min_payout_cents(l.affiliate_id)]


def describe_rate(rule: dict) -> str:
    if rule["type"] == "percent":
        return f"{rule['bps'] / 100:g}%"
    if rule["type"] == "flat":
        return f"{rule['cents'] / 100:.2f} {rule['currency'].upper()}"
    return "no commission"


REWARD_TRIGGERS = {"signup": "when a referral signs up", "first_payment": "when a referral first pays", "every_payment": "for every payment from a referral"}


def is_custom(campaign: dict | None) -> bool:
    return ((campaign or {}).get("reward") or {}).get("type") == "custom"


def describe_reward(campaign: dict) -> str:
    r = campaign["reward"]
    a = r["affiliate"]
    text = f"{a['description']} {REWARD_TRIGGERS[a['on']]}"
    if a["limit"] == "once":
        text += ", once"
    if c := r.get("customer"):
        text += f"; the referred customer gets {c['description']} {'at signup' if c['on'] == 'signup' else 'when they first pay'}"
    return text


def describe_rule(campaign: dict, affiliate: dict | None = None) -> str:
    if is_custom(campaign):
        return describe_reward(campaign)
    rule, duration = effective_rule(campaign, affiliate), campaign["duration"]
    rate = describe_rate(rule)
    if duration["mode"] == "once":
        text = f"{rate} of the first payment"
    elif duration["mode"] == "forever":
        text = f"{rate} of every payment, for life"
    else:
        text = f"{rate} of every payment for {duration['months']} months"
    if (b := campaign.get("lead_bounty")) and b.get("cents"):
        text += f", plus {b['cents'] / 100:.2f} {b['currency'].upper()} per signup"
    return text
