from datetime import UTC, datetime, timedelta

from app.domain.commission import add_months, decide_commission, decide_refund, describe_rule, payable_lines
from app.domain.fraud import canonical_email, self_referral_flags

T0 = datetime(2026, 1, 31, tzinfo=UTC)
PCT = {"rule": {"type": "percent", "bps": 3000}, "duration": {"mode": "months", "months": 12}, "hold_days": 30}


def test_percent_commission_with_hold():
    d = decide_commission(PCT, 10_000, "USD", T0, T0, 0)
    assert d.ok and d.amount_cents == 3000 and d.currency == "usd"
    assert d.due_at == T0 + timedelta(days=30)


def test_month_window_is_calendar_aware():
    assert add_months(T0, 1) == datetime(2026, 2, 28, tzinfo=UTC)
    inside = decide_commission(PCT, 10_000, "usd", add_months(T0, 12) - timedelta(seconds=1), T0, 5)
    outside = decide_commission(PCT, 10_000, "usd", add_months(T0, 12), T0, 5)
    assert inside.ok and not outside.ok


def test_once_and_flat():
    flat = {"rule": {"type": "flat", "cents": 2500, "currency": "usd"}, "duration": {"mode": "once"}, "hold_days": 0}
    assert decide_commission(flat, 999, "eur", T0, T0, 0).amount_cents == 2500
    assert decide_commission(flat, 999, "eur", T0, T0, 0).currency == "usd"
    assert not decide_commission(flat, 999, "usd", T0, T0, 1).ok
    assert not decide_commission(PCT, 0, "usd", T0, T0, 0).ok


def test_partial_refunds_add_up_and_paid_ones_claw_back():
    # 3000 commission on a 10000 charge, refunded 2500 then 7500
    a = decide_refund("pending", 3000, 3000, 2500, 10_000)
    assert a.kind == "reduce" and a.amount_cents == 2250
    b = decide_refund("pending", 3000, 2250, 7500, 10_000)
    assert b.kind == "void"
    c = decide_refund("paid", 3000, 3000, 5000, 10_000)
    assert c.kind == "clawback" and c.amount_cents == -1500
    assert decide_refund("void", 3000, 0, 100, 10_000).kind == "none"


def test_payable_nets_clawbacks_and_respects_hold_threshold_and_review():
    now = T0 + timedelta(days=60)
    rows = [
        {"_id": "1", "affiliate_id": "a", "currency": "usd", "amount_cents": 6000, "status": "pending", "due_at": T0},
        {"_id": "2", "affiliate_id": "a", "currency": "usd", "amount_cents": -1500, "status": "pending", "due_at": T0},
        {"_id": "3", "affiliate_id": "a", "currency": "usd", "amount_cents": 9999, "status": "pending", "due_at": now + timedelta(days=1)},
        {"_id": "4", "affiliate_id": "b", "currency": "usd", "amount_cents": 1000, "status": "pending", "due_at": T0},
        {"_id": "5", "affiliate_id": "c", "currency": "usd", "amount_cents": 9000, "status": "pending", "due_at": T0, "held": True},
        {"_id": "6", "affiliate_id": "a", "currency": "eur", "amount_cents": 7000, "status": "paid", "due_at": T0},
    ]
    lines = payable_lines(rows, now, lambda aff: 2000)
    assert [(l.affiliate_id, l.amount_cents, l.commission_ids) for l in lines] == [("a", 4500, ["1", "2"])]


def test_describe():
    assert describe_rule(PCT) == "30% of every payment for 12 months"


def test_self_referral_signals():
    assert canonical_email("M.ark+promo@GoogleMail.com") == "mark@gmail.com"
    kinds = lambda f: sorted(x["kind"] for x in f)  # noqa: E731
    assert kinds(self_referral_flags("mark@gmail.com", [], "m.ark+1@gmail.com", None)) == ["self_email"]
    assert kinds(self_referral_flags("mark@acme.io", [], "bob@acme.io", None)) == ["self_domain"]
    assert kinds(self_referral_flags("mark@gmail.com", [], "bob@gmail.com", None)) == []
    assert kinds(self_referral_flags("mark@gmail.com", ["h1"], "bob@x.com", "h1")) == ["self_ip"]
