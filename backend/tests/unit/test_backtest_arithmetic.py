"""Backtest arithmetic on a hand-built 6-order frame (§4 StrategyBacktest), policy v1.0 values.

Order  V       CLV     truth                         action          realized cost (hand-computed)
1      10,000  2,000   abusive, full return           BLOCK           0
2      4,000   5,000   abusive, item-not-received     MANUAL_REVIEW   0.2 × (3,400 + 150) + 250 = 960
3      2,000   2,000   abusive, partial return 0.5    PREPAID_ONLY    0.7 × (1,000 + 150) × 0.5 = 402.5
4      1,000   10,000  genuine                        BLOCK           300 + 0.6 × 10,000 + 100 = 6,400
5      5,000   3,000   genuine                        MANUAL_REVIEW   0.05 × 1,500 + 0.03 × (1,500 + 1,800 + 100) + 250 = 427
6      3,000   1,000   genuine (CLV floor 2,000)      PREPAID_ONLY    0.08 × 900 + 0.02 × 2,000 + 30 = 142
"""
import numpy as np
import pandas as pd
import pytest

from sentinel.evaluation import backtest as B
from sentinel.policy.config import load_policy_config

CFG = load_policy_config()
ROWS = pd.DataFrame({
    "order_value_inr": [10_000.0, 4_000.0, 2_000.0, 1_000.0, 5_000.0, 3_000.0],
    "clv_inr": [2_000.0, 5_000.0, 2_000.0, 10_000.0, 3_000.0, 1_000.0],
    "return_label": pd.array([1, 0, 1, 0, 1, 0], dtype="Int64"),
    "returned_value_fraction": [1.0, 0.0, 0.5, 0.0, 1.0, np.nan],
})
LABELS = [1, 1, 1, 0, 0, 0]
ACTIONS = np.array([B.BLOCK, B.REVIEW, B.PREPAID, B.BLOCK, B.REVIEW, B.PREPAID])


@pytest.fixture(scope="module")
def cm():
    return B.cost_matrix(ROWS, LABELS, CFG)


def test_realized_costs_per_order(cm):
    assert B.realized_costs(cm, ACTIONS) == pytest.approx([0.0, 960.0, 402.5, 6_400.0, 427.0, 142.0])
    # ALLOW on the abusive orders: V × 0.85 + 150, scaled by the returned fraction
    assert cm.total[:3, B.ALLOW] == pytest.approx([8_650.0, 3_550.0, 925.0])
    assert cm.total[3:, B.ALLOW] == pytest.approx([0.0, 0.0, 0.0])


def test_item_not_received_claim_is_not_scaled_by_a_zero_fraction():
    assert B.loss_fraction(ROWS["return_label"], ROWS["returned_value_fraction"]).tolist() == \
        [1.0, 1.0, 0.5, 1.0, 1.0, 1.0]


def test_every_strategy_backtest_field(cm):
    result, extras = B.strategy_backtest("SENTINEL", ACTIONS, cm, CFG)
    total = 0 + 960 + 402.5 + 6_400 + 427 + 142                               # 8,331.5
    assert result.realized_cost_per_1000.inr == pytest.approx(round(1000 * total / 6, 2))      # 13,88,583.33
    assert result.realized_cost_per_1000.display == "₹13,88,583"
    assert result.abuse_loss_prevented.inr == pytest.approx((8_650 - 0) + (3_550 - 960) + (925 - 402.5))  # 11,762.5
    assert result.genuine_block_rate == pytest.approx(1 / 3)
    assert result.customer_friction_rate == pytest.approx(2 / 3)
    assert result.manual_reviews_per_1000 == pytest.approx(1000 * 2 / 6)
    intercepted = 1 + 0.80 + 0.30                                              # BLOCK, REVIEW, PREPAID
    assert extras["expected_intercepted_abusive"] == pytest.approx(intercepted)
    side_costs = 250 + 6_400 + 427 + 142                                       # operational + genuine branch
    assert result.cost_per_detected_abuse.inr == pytest.approx(round(side_costs / intercepted, 2))   # 3,437.62
    assert result.revenue_preserved.inr == pytest.approx(300 * 0 + 1_500 * (1 - 0.08) + 900 * (1 - 0.08))  # 2,208
    assert result.precision_block == pytest.approx(1 / 2)
    assert result.recall_intercepted == pytest.approx(intercepted / 3)
    assert extras["notes"] == []


def test_allow_all_on_the_same_frame(cm):
    result, extras = B.strategy_backtest("ALLOW_ALL", B.allow_all_actions(6), cm, CFG)
    assert result.realized_cost_per_1000.inr == pytest.approx(round(1000 * (8_650 + 3_550 + 925) / 6, 2))
    assert result.abuse_loss_prevented.inr == 0
    assert result.revenue_preserved.inr == pytest.approx(300 + 1_500 + 900)
    assert (result.genuine_block_rate, result.customer_friction_rate, result.recall_intercepted) == (0, 0, 0)
    assert result.cost_per_detected_abuse.inr == 0 and result.precision_block == 0
    assert len(extras["notes"]) == 2                                            # both undefined ratios noted


def test_threshold_actions_match_the_baseline_function():
    p = np.linspace(0, 1, 101)
    for tau_review, tau_block in [(0.1, 0.5), (0.3, 0.3), (0.05, 0.95)]:
        assert (B.threshold_actions(p, tau_review, tau_block) ==
                B.fixed_threshold_actions(p, tau_review, tau_block)).all()


def test_tuning_refuses_rows_outside_calibration(cm):
    rows = ROWS.assign(split=["CALIBRATION"] * 5 + ["TEST"], order_id=[f"ORD-{i}" for i in range(6)])
    with pytest.raises(AssertionError, match="CALIBRATION"):
        B.tune_fixed_threshold(rows, np.full(6, 0.5), cm)


def test_tuning_picks_the_cheapest_pair(cm):
    rows = ROWS.assign(split="CALIBRATION", order_id=[f"ORD-{i}" for i in range(6)])
    p = np.array([0.9, 0.6, 0.3, 0.02, 0.02, 0.02])
    tuning = B.tune_fixed_threshold(rows, p, cm)
    # abusive orders are caught by BLOCK when p >= tau_block; genuine ones are never touched below 0.05
    assert tuning.tau_block <= 0.3 and tuning.tau_review <= tuning.tau_block
    assert tuning.realized_cost_per_1000 == pytest.approx(0.0)
    assert tuning.order_ids == tuple(rows["order_id"])


def test_scaled_config_clips_rates():
    cfg = B.scaled_config(CFG, "manual_review", 1.5)
    assert cfg.manual_review.reviewer_detection_rate == 1.0
    assert cfg.manual_review.review_cost_inr == pytest.approx(375)
    assert cfg.prepaid_only == CFG.prepaid_only and cfg.config_sha256 != CFG.config_sha256


def test_threshold_of_one_means_never():
    p = np.array([0.2, 0.99, 1.0])
    assert B.fixed_threshold_actions(p, 1.0, 1.0).tolist() == [B.ALLOW] * 3
    assert B.threshold_actions(p, 0.1, 1.0).tolist() == [B.REVIEW] * 3
    assert B.TAU_GRID[0] == 0.05 and B.TAU_GRID[-1] == 1.0 and len(B.TAU_GRID) == 20


def test_unconstrained_action_is_the_expected_cost_argmin():
    rows = ROWS.assign(clv_inr=2_000.0)
    p = np.array([0.95, 0.5, 0.01, 0.95, 0.5, 0.01])
    actions = B.unconstrained_actions(rows, p, CFG)
    assert actions[0] == B.BLOCK and actions[2] == B.ALLOW
