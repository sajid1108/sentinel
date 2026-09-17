"""§11 demo bands through the committed artifacts (Phase 4 gate): replay to DEMO_CLOCK, features_for_request,
calibrated p_return and p_abuse, decide(). The bands and actions are asserted; probabilities are never set."""
import pytest

from sentinel.api.schemas import Action
from sentinel.evaluation.demos import score_demos
from sentinel.features.builder import WORLD_TABLES
from sentinel.models import registry
from sentinel.policy.config import load_policy_config
from sentinel.policy.costs import action_costs

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def scored(world):
    bundles = {name: registry.load_bundle(name) for name in registry.MODEL_NAMES}
    return {d.order_id: d for d in score_demos(bundles, load_policy_config(), {t: world[t] for t in WORLD_TABLES})}


def test_demo_1_frequent_returner_allow(scored):
    d = scored["ORD-DEMO-001"]
    assert 0.0 <= d.p_abuse <= 0.15 and d.p_abuse < 0.10
    assert d.p_return >= 0.55
    assert d.decision.selected_action is Action.ALLOW


def test_demo_2_ring_member_block(scored):
    d = scored["ORD-DEMO-002"]
    assert 0.75 <= d.p_abuse <= 1.0
    assert d.decision.selected_action is Action.BLOCK


# §11 Demo 3 as amended by the architect (deviation #26): the device is shared concurrently with 3 other
# accounts in the last 30 days, none confirmed. All four required outcomes are asserted here.
DEMO_3_COST_MARGIN = 0.15
# The band is a guard on the measured score, not the property under test: what matters is that
# MANUAL_REVIEW is the right action and that cost - not a guardrail - selects it. Widened from 0.70 so the
# demo is not one retrain away from a red suite, then held at 0.84 - just under the measured cost-optimality
# crossover 0.8413 - so the band can never pass while the cost assertion below fails (#26).
DEMO_3_BAND = (0.20, 0.84)
# Cost-optimality grid for Demo 3's own order value and CLV, guardrails not applied. MANUAL_REVIEW is
# cost-optimal on every point below and not at 0.90; the measured crossover is recorded in #26.
DEMO_3_REVIEW_OPTIMAL_AT = (0.20, 0.40, 0.60, 0.6913, 0.75, 0.83)
DEMO_3_REVIEW_NOT_OPTIMAL_AT = 0.90


def test_demo_3_uncertain_middle_manual_review(scored):
    d = scored["ORD-DEMO-003"]
    assert DEMO_3_BAND[0] <= d.p_abuse <= DEMO_3_BAND[1]                          # 1 band
    assert d.decision.selected_action is Action.MANUAL_REVIEW                     # 2 action


def test_demo_3_counted_signals_and_guardrails(scored):
    d = scored["ORD-DEMO-003"]
    assert list(d.counted_signals) == ["DEVICE", "ACCOUNT_CLAIMS"]                # 3 counted signals
    # exactly one linked order in 24 h: TEMPORAL_BURST needs >= 3 and must stay absent
    assert "TEMPORAL_BURST" not in d.counted_signals
    assert d.features["linked_orders_24h"] == 1
    costs = {c.action: c for c in d.decision.costs}
    # two counted signals with an anchor means G2 passes; only G3 removes BLOCK
    assert tuple(costs[Action.BLOCK].excluded_by) == ("G3",)


def test_demo_3_allow_review_cost_margin(scored):
    d = scored["ORD-DEMO-003"]
    costs = {c.action: c.expected_cost.inr for c in d.decision.costs}
    allow, review = costs[Action.ALLOW], costs[Action.MANUAL_REVIEW]
    assert allow - review >= DEMO_3_COST_MARGIN * review                          # 4 margin


def _cheapest(p: float, order_value_inr: float, clv_inr: float) -> Action:
    """Cost-optimal action with no guardrails applied: cost alone, over all four actions."""
    costs = action_costs(p, order_value_inr, clv_inr, load_policy_config())
    return min(costs, key=lambda a: costs[a].total)


def test_demo_3_manual_review_is_cost_optimal_not_guardrail_driven(scored):
    """Demo 3 gets MANUAL_REVIEW because it is the cheapest action, not because G3 removed BLOCK.
    At the live score BLOCK costs roughly twice MANUAL_REVIEW, so removing every guardrail changes
    nothing. Above the crossover (#26) BLOCK does become cheapest, which 0.90 pins down."""
    d = scored["ORD-DEMO-003"]
    v, clv = d.features["order_value_inr"], d.clv_inr
    for p in (*DEMO_3_REVIEW_OPTIMAL_AT, d.p_abuse):
        assert _cheapest(p, v, clv) is Action.MANUAL_REVIEW, f"p={p}"
    assert _cheapest(DEMO_3_REVIEW_NOT_OPTIMAL_AT, v, clv) is Action.BLOCK
    # the engine's own cost-optimal action agrees at the live score
    assert d.decision.cost_optimal_action is Action.MANUAL_REVIEW
