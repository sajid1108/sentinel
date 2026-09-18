"""§9.5 baselines."""
import pytest

from sentinel.api.schemas import Action
from sentinel.policy.baselines import allow_all, fixed_threshold, rule_based


@pytest.mark.parametrize("p, expected", [(0.9, Action.BLOCK), (0.8, Action.BLOCK), (0.5, Action.MANUAL_REVIEW),
                                         (0.3, Action.MANUAL_REVIEW), (0.29, Action.ALLOW)])
def test_fixed_threshold(p, expected):
    outcome = fixed_threshold(p, tau_block=0.8, tau_review=0.3)
    assert outcome.strategy == "FIXED_THRESHOLD"
    assert outcome.action is expected


def test_fixed_threshold_rejects_inverted_thresholds():
    with pytest.raises(ValueError):
        fixed_threshold(0.5, tau_block=0.3, tau_review=0.8)


def test_rule_based_blocks_demo_1_loyal_returner():
    outcome = rule_based(matured_return_rate=0.58, matured_returns=30, account_age_days=1280,
                         order_value_inr=4500, payment_method="PREPAID_UPI")
    assert outcome.action is Action.BLOCK


def test_rule_based_reviews_demo_2_ring_member():
    outcome = rule_based(matured_return_rate=None, matured_returns=0, account_age_days=6,
                         order_value_inr=24000, payment_method="PREPAID_CARD")
    assert outcome.action is Action.MANUAL_REVIEW


def test_rule_based_lets_ring_cover_order_through():
    outcome = rule_based(matured_return_rate=None, matured_returns=0, account_age_days=6,
                         order_value_inr=14999, payment_method="PREPAID_CARD")
    assert outcome.action is Action.ALLOW


@pytest.mark.parametrize("rate, returns, expected", [(0.5, 5, Action.BLOCK), (0.5, 4, Action.ALLOW),
                                                     (0.49, 20, Action.ALLOW)])
def test_rule_based_return_rule_needs_rate_and_count(rate, returns, expected):
    assert rule_based(rate, returns, 400, 1000, "PREPAID_UPI").action is expected


def test_rule_based_cod_prepaid():
    assert rule_based(0.1, 1, 400, 5000, "COD").action is Action.PREPAID_ONLY
    assert rule_based(0.1, 1, 400, 4999, "COD").action is Action.ALLOW


def test_allow_all():
    assert allow_all() is Action.ALLOW


# ── reviewer-facing wording (Phase 9 brief 1.3) ─────────────────────────────
def test_fixed_threshold_rule_text_uses_the_pages_probability_format():
    """The rule a reviewer reads beside the baseline's action, in the page's own format."""
    assert fixed_threshold(0.95, tau_block=0.75, tau_review=0.35).rule_fired == "abuse probability >= 75.0%"
    assert fixed_threshold(0.50, tau_block=0.75, tau_review=0.35).rule_fired == "abuse probability >= 35.0%"
    assert fixed_threshold(0.10, tau_block=0.75, tau_review=0.35).rule_fired == "abuse probability < 35.0%"


def test_no_baseline_rule_text_names_a_raw_variable():
    for p in (0.0, 0.1, 0.5, 0.9, 1.0):
        assert "p_abuse" not in fixed_threshold(p, tau_block=0.75, tau_review=0.35).rule_fired
