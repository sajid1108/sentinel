"""§11 demo bands through the committed artifacts (Phase 4 gate): replay to DEMO_CLOCK, features_for_request,
calibrated p_return and p_abuse, decide(). The bands and actions are asserted; probabilities are never set."""
import pytest

from sentinel.api.schemas import Action
from sentinel.evaluation.demos import score_demos
from sentinel.features.builder import WORLD_TABLES
from sentinel.models import registry
from sentinel.policy.config import load_policy_config

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


def test_demo_3_uncertain_middle_manual_review(scored):
    d = scored["ORD-DEMO-003"]
    assert 0.20 <= d.p_abuse <= 0.70                                              # 1 band
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
