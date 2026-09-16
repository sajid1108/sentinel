"""§9.1 decision algorithm: tie-break, property check, explanation, status, slope validator."""
import random
from dataclasses import replace
from datetime import timedelta

import pytest

from sentinel.api.schemas import SEVERITY, Action
from sentinel.policy.config import check_slope_order, load_policy_config
from sentinel.policy.engine import argmin_with_tiebreak, decide, decision_status
from sentinel.policy.guardrails import SignalInputs
from sentinel.settings import DEMO_CLOCK

from .policy_helpers import DEMO_1, DEMO_2, DEVICE, by_action, ctx

CFG = load_policy_config()


# ── Tie-break ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("totals, expected", [
    ({Action.ALLOW: 100.0, Action.PREPAID_ONLY: 100.0, Action.MANUAL_REVIEW: 100.0, Action.BLOCK: 100.0}, Action.ALLOW),
    ({Action.ALLOW: 900.0, Action.PREPAID_ONLY: 500.0, Action.MANUAL_REVIEW: 499.5, Action.BLOCK: 499.0}, Action.PREPAID_ONLY),
    ({Action.ALLOW: 900.0, Action.PREPAID_ONLY: 500.0, Action.MANUAL_REVIEW: 499.0, Action.BLOCK: 800.0}, Action.PREPAID_ONLY),
    ({Action.ALLOW: 900.0, Action.PREPAID_ONLY: 500.01, Action.MANUAL_REVIEW: 499.0, Action.BLOCK: 800.0}, Action.MANUAL_REVIEW),
])
def test_ties_go_to_less_severe_action(totals, expected):
    assert argmin_with_tiebreak(totals, set(Action), CFG) is expected


def test_engine_tie_at_cost_crossing_picks_less_severe():
    """Demo 1 economics: bisect p where ALLOW and MANUAL_REVIEW cost the same (§11: p ~ 0.235); must pick ALLOW."""
    from sentinel.policy.costs import action_costs

    def gap(p):
        c = action_costs(p, DEMO_1["order_value_inr"], DEMO_1["clv_inr"], CFG)
        return c[Action.ALLOW].total - c[Action.MANUAL_REVIEW].total

    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if gap(mid) < 0 else (lo, mid)
    d = decide(ctx(lo, **DEMO_1), CFG)
    costs = by_action(d)
    assert abs(costs[Action.ALLOW].expected_cost.inr - costs[Action.MANUAL_REVIEW].expected_cost.inr) <= 1.0
    assert lo == pytest.approx(0.235, abs=0.001)
    assert d.selected_action is Action.ALLOW
    assert "ties go to the less severe action" in d.policy_explanation


# ── Property check: feasible set never empty, contract validator always satisfied ──
def _random_signals(rng: random.Random) -> SignalInputs:
    return SignalInputs(
        device_confirmed_abuse_weight=rng.choice([0.0, rng.uniform(0, 2)]),
        device_other_accounts_30d=rng.randint(0, 6),
        device_weight=rng.random(),
        token_other_accounts_30d=rng.randint(0, 4),
        token_weight=rng.random(),
        address_is_multi_tenant=rng.random() < 0.3,
        address_confirmed_abuse_weight=rng.uniform(0, 1),
        address_weight=rng.random(),
        linked_orders_24h=rng.randint(0, 6),
        linked_same_sku_7d=rng.randint(0, 3),
        burst_link_kinds=frozenset(k for k in ("DEVICE", "PAYMENT_TOKEN", "ADDRESS") if rng.random() < 0.4),
        burst_weight=rng.random(),
        prior_suspicious_claims_180d=rng.randint(0, 2),
    )


def _random_config(rng: random.Random):
    """Valid-range perturbations of every rate, so the invariants hold beyond v1.0 values."""
    def rate():
        return rng.uniform(0.0, 1.0)
    return replace(
        CFG,
        economics=replace(CFG.economics, gross_margin_rate=rate(), reverse_logistics_cost_inr=rng.uniform(0, 500)),
        allow=replace(CFG.allow, abuse_recovery_rate=rate()),
        prepaid_only=replace(CFG.prepaid_only, abuser_deterrence_rate=rate(), abuse_recovery_rate=rate(),
                             genuine_abandonment_rate=rate(), genuine_clv_churn_rate=rate(),
                             genuine_friction_cost_inr=rng.uniform(0, 200)),
        manual_review=replace(CFG.manual_review, review_cost_inr=rng.uniform(0, 1000),
                              reviewer_detection_rate=rng.uniform(0.01, 1.0),
                              genuine_delay_abandonment_rate=rate(), genuine_false_cancel_rate=rate()),
        block=replace(CFG.block, genuine_clv_churn_rate=rate(), genuine_support_cost_inr=rng.uniform(0, 500)),
    )


def test_ten_thousand_random_contexts():
    rng = random.Random(20260901)
    selected_seen = set()
    for i in range(10_000):
        cfg = CFG if i % 2 == 0 else _random_config(rng)
        degraded = rng.random() < 0.05
        c = ctx(
            p_abuse=None if degraded else rng.random(),
            order_value_inr=rng.uniform(1, 500_000),
            clv_inr=rng.uniform(0, 300_000),
            signals=_random_signals(rng),
            p_return=None if degraded else rng.random(),
            graph_state_as_of=DEMO_CLOCK - timedelta(hours=rng.uniform(0, 48)),
            degraded=degraded,
        )
        d = decide(c, cfg)   # PolicyDecision's model validator runs here
        selected_seen.add(d.selected_action)
        if degraded:
            assert d.costs == [] and d.cost_optimal_action is None and d.selected_action is not Action.BLOCK
            continue
        costs = by_action(d)
        assert costs[Action.PREPAID_ONLY].feasible and costs[Action.MANUAL_REVIEW].feasible
        assert len(d.costs) == 4 and sorted(x.rank_by_cost for x in d.costs) == [1, 2, 3, 4]
        if costs[Action.BLOCK].feasible:
            assert c.p_abuse >= 0.70
    assert selected_seen == set(Action)


# ── Explanation and status ──────────────────────────────────────────────────
def test_demo_2_with_only_device_signal_is_held_by_guardrails():
    d = decide(ctx(0.91, **DEMO_2, signals=DEVICE), CFG)
    assert d.cost_optimal_action is Action.BLOCK
    assert d.selected_action is Action.MANUAL_REVIEW
    assert d.selected_rule == "MIN_EXPECTED_COST_WITHIN_GUARDRAILS"
    assert d.policy_explanation.startswith(
        "BLOCK had the lowest expected cost (₹765) but was not permitted: "
        "G2 requires two corroborating signals; one was found.")


def test_policy_explanation_matches_section_6_5_example():
    from .policy_helpers import DEMO_3, DEMO_3_SIGNALS

    d = decide(ctx(0.45, **DEMO_3, signals=DEMO_3_SIGNALS), CFG)
    assert d.policy_explanation.startswith(
        "MANUAL_REVIEW was selected because its expected cost (₹1,490) is lower than "
        "PREPAID_ONLY (₹2,277), ALLOW (₹4,658) and BLOCK (₹6,985) under policy v1.0.")
    assert "G2 requires two corroborating signals; one was found." in d.policy_explanation
    assert d.assumptions_notice == "Monetary values are demonstration assumptions (policy v1.0)."
    assert d.policy_config_sha256 == CFG.config_sha256


@pytest.mark.parametrize("action, status", [
    (Action.ALLOW, "AUTO_APPLIED"), (Action.PREPAID_ONLY, "AUTO_APPLIED"),
    (Action.MANUAL_REVIEW, "PENDING_REVIEW"), (Action.BLOCK, "AUTO_APPLIED"),
])
def test_decision_status(action, status):
    assert decision_status(action) == status


# ── §8.4 slope-order validator ──────────────────────────────────────────────
def test_slope_validator_reports_prepaid_review_swap_as_info():
    report = check_slope_order(CFG)
    assert report.errors == ()
    assert len(report.info) == 1 and "PREPAID_ONLY" in report.info[0] and "MANUAL_REVIEW" in report.info[0]
    swaps = {(v.order_value_inr, v.clv_inr) for v in report.violations
             if (v.higher, v.lower) == ("PREPAID_ONLY", "MANUAL_REVIEW")}
    assert (500.0, 100000.0) in swaps
    assert all(v.order_value_inr < 845 for v in report.violations)
    # Analytic form from §8.4: slope(PREPAID) - slope(REVIEW) = 0.18 V + 48 - 0.002 CLV
    at_corner = next(v for v in report.violations if (v.order_value_inr, v.clv_inr) == (500.0, 100000.0))
    assert at_corner.slope_gap_inr == pytest.approx(0.18 * 500 + 48 - 0.002 * 100000)


def test_slope_validator_does_not_block_loading_v1():
    assert load_policy_config().policy.version == "v1.0"


def test_slope_violation_outside_accepted_swap_is_an_error():
    from sentinel.policy.config import validate_policy_config

    # slope(REVIEW) - slope(BLOCK) = (1 - detection) L_allow - delay_abandon M + (1 - false_cancel) FB:
    # negative with perfect detection, certain false cancel and any delay abandonment.
    bad = replace(CFG, manual_review=replace(CFG.manual_review, reviewer_detection_rate=1.0,
                                             genuine_delay_abandonment_rate=0.5, genuine_false_cancel_rate=1.0))
    report = check_slope_order(bad)
    assert report.errors
    assert any("slope(MANUAL_REVIEW) < slope(BLOCK)" in e for e in validate_policy_config(bad))


def test_severity_monotone_in_p_outside_swap_region():
    report = check_slope_order(CFG)
    swapped = {(v.order_value_inr, v.clv_inr) for v in report.violations}
    for v in (1000, 4500, 12000, 24000, 200000):
        for clv in (2000, 15000, 30000, 100000):
            assert (v, clv) not in swapped
            severities = [SEVERITY[decide(ctx(i / 100, order_value_inr=v, clv_inr=clv), CFG).cost_optimal_action]
                          for i in range(101)]
            assert severities == sorted(severities), (v, clv)
