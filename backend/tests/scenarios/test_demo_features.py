"""§11 demo feature values through the serving path, and the policy decision they lead to.

Features are computed at DEMO_CLOCK - 5 min on a builder replayed to DEMO_CLOCK. Probabilities are
the §11 targets (models are Phase 4); everything else comes from the real feature builder.
"""
import pytest

from sentinel.api.schemas import Action, ScoreOrderRequest
from sentinel.data import demo_orders as D
from sentinel.features.builder import FeatureBuilder
from sentinel.features.graph_state import node_id, to_micros
from sentinel.policy.config import load_policy_config
from sentinel.policy.engine import decide
from sentinel.policy.guardrails import DecisionContext, corroborating_signals
from sentinel.settings import DEMO_CLOCK

pytestmark = pytest.mark.slow
T0 = D.DEMO_PLACED_AT


@pytest.fixture(scope="module")
def builder(world):
    return FeatureBuilder.replay(world, DEMO_CLOCK)


@pytest.fixture(scope="module")
def demos(builder):
    out = {}
    for payload in D.demo_requests():
        req = ScoreOrderRequest.model_validate(payload)
        inputs = builder.signal_inputs(req, T0)
        out[req.order_id] = {
            "request": req,
            "features": builder.features_for_request(req, T0),
            "inputs": inputs,
            "signals": corroborating_signals(inputs),
            "counted": [s.signal for s in corroborating_signals(inputs) if s.present and s.counts_for_corroboration],
            "links": builder.discounted_links(req, T0),
            "clv": builder.clv_inr(req.account_id, T0),
        }
    return out


def test_graph_state_as_of_is_the_replay_time(builder):
    assert builder.graph_state_as_of == DEMO_CLOCK


def test_demo_1(demos):
    d = demos["ORD-DEMO-001"]
    f = d["features"]
    assert f["account_age_days"] == pytest.approx(1280, abs=0.01)
    assert f["prior_orders"] == 52
    assert f["prior_suspicious_claims_180d"] == 0
    assert f["device_other_accounts_30d"] == 0 and f["token_other_accounts_30d"] == 0
    assert f["device_confirmed_abuse_weight"] == 0
    assert [(link.kind, link.reason) for link in d["links"]] == [("ADDRESS", "HOUSEHOLD_PATTERN")]
    assert d["links"][0].weight == pytest.approx(0.13, abs=0.01)
    assert d["clv"] == pytest.approx(30_000, rel=0.20)
    assert d["counted"] == []


def test_demo_2(demos, builder):
    d = demos["ORD-DEMO-002"]
    f = d["features"]
    assert f["account_age_days"] == pytest.approx(6, abs=0.01)
    assert f["prior_orders"] == 0
    assert f["device_other_accounts_30d"] == 5
    assert f["device_confirmed_abuse_weight"] >= 0.3
    device = node_id("DEVICE", d["request"].device_id)
    confirmed = [a for a in builder.state.identifier_accounts(device)
                 if (builder.state.accounts[a].confirmed_at or float("inf")) < to_micros(T0)]
    assert len(confirmed) == 3
    assert f["token_other_accounts_30d"] == 3
    assert f["linked_orders_24h"] == 4
    assert f["linked_same_sku_7d"] == 3
    assert f["component_size_reliable_90d"] == 8
    assert f["component_abuse_ratio_smoothed"] == pytest.approx(0.222, abs=0.001)
    assert d["clv"] == 2000
    assert d["counted"] == ["DEVICE", "PAYMENT_TOKEN", "TEMPORAL_BURST"]
    assert d["links"] == []


def test_demo_3(demos):
    d = demos["ORD-DEMO-003"]
    f = d["features"]
    assert f["account_age_days"] == pytest.approx(240, abs=0.01)
    assert f["prior_orders"] == 7
    assert f["prior_suspicious_claims_180d"] == 1
    assert f["device_other_accounts_30d"] == 1 and f["device_confirmed_abuse_weight"] == 0
    assert d["inputs"].address_confirmed_abuse_weight == pytest.approx(0.04, abs=0.005)
    assert [(link.kind, link.reason) for link in d["links"]] == [("ADDRESS", "STALE_RELATIONSHIP")]
    assert d["clv"] == pytest.approx(15_000, rel=0.20)
    assert d["counted"] == ["ACCOUNT_CLAIMS"]


@pytest.mark.parametrize("order_id,p_abuse,p_return,expected", [
    ("ORD-DEMO-001", 0.03, 0.75, Action.ALLOW),
    ("ORD-DEMO-002", 0.91, 0.30, Action.BLOCK),
    ("ORD-DEMO-003", 0.45, 0.30, Action.MANUAL_REVIEW),
])
def test_policy_integration(demos, builder, order_id, p_abuse, p_return, expected):
    d = demos[order_id]
    ctx = DecisionContext(p_abuse=p_abuse, p_return=p_return, order_value_inr=d["features"]["order_value_inr"],
                          clv_inr=d["clv"], signals=d["signals"], decided_at=DEMO_CLOCK,
                          graph_state_as_of=builder.graph_state_as_of)
    assert decide(ctx, load_policy_config()).selected_action == expected
