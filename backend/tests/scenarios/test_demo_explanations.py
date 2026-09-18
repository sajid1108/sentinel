"""§11 demo explanations through the committed artifacts and the real FeatureBuilder (§6.5, #27).

Nothing here sets a probability: every number comes from the committed models scoring the real demo
feature rows. The assertions are about which evidence is reported and how, not about the score.
"""
import pytest

from sentinel.api.schemas import ScoreOrderRequest
from sentinel.data import demo_orders as D
from sentinel.features import definitions
from sentinel.features.builder import FeatureBuilder
from sentinel.models import registry
from sentinel.models.explain import explain_order, explanation_group
from sentinel.policy.config import load_policy_config
from sentinel.settings import DEMO_CLOCK

pytestmark = pytest.mark.slow
T0 = D.DEMO_PLACED_AT

# §11 Demo 2: the counterfactual must visibly collapse the score, or the graph story is not real.
DEMO_2_MIN_GRAPH_DROP = 0.40


@pytest.fixture(scope="module")
def bundles():
    return {name: registry.load_bundle(name) for name in registry.MODEL_NAMES}


@pytest.fixture(scope="module")
def explanations(world, bundles):
    reference = registry.load_reference(bundles)
    builder = FeatureBuilder.replay(world, DEMO_CLOCK)
    out = {}
    for payload in D.demo_requests():
        request = ScoreOrderRequest.model_validate(payload)
        out[request.order_id] = explain_order(
            bundles, reference, builder.features_for_request(request, T0),
            builder.discounted_links(request, T0))
    return out


def _codes(explanation):
    return {r.code for r in explanation.reasons}


def _graph_codes(explanation):
    return {c for c in _codes(explanation) if c.startswith("GRAPH_")}


# -- Demo 1: legitimate frequent returner ------------------------------------
def test_demo_1_has_no_graph_codes(explanations):
    assert _graph_codes(explanations["ORD-DEMO-001"]) == set()


def test_demo_1_has_a_mitigating_code(explanations):
    assert explanations["ORD-DEMO-001"].mitigating_reasons


def test_demo_1_explanation_is_account_dominant(explanations):
    e = explanations["ORD-DEMO-001"]
    assert explanation_group(e.group_attribution_pp) == "account"


def test_demo_1_return_codes_do_not_claim_abuse(explanations):
    """§6.5: the return story is operational context and must say so, not imply abuse."""
    texts = [r.reviewer_text for r in explanations["ORD-DEMO-001"].reasons if r.model == "RETURN"]
    assert texts and any("not abuse risk" in t for t in texts)


# -- Demo 2: coordinated ring member -----------------------------------------
def test_demo_2_fires_the_three_graph_codes(explanations):
    assert {"GRAPH_DEVICE_CONFIRMED_LINK", "GRAPH_TOKEN_REUSE", "TEMPORAL_BURST"} <= _codes(
        explanations["ORD-DEMO-002"])


def test_demo_2_explanation_is_graph_dominant(explanations):
    e = explanations["ORD-DEMO-002"]
    assert explanation_group(e.group_attribution_pp) == "graph"


def test_demo_2_confirmed_device_code_carries_the_redundancy_note(explanations):
    """#27: the confirmed-device link is real evidence and fires, but a correlated feature already
    carries it in the score, so the code says so instead of vanishing."""
    from sentinel.models.reason_codes import REDUNDANT_NOTE
    code = next(r for r in explanations["ORD-DEMO-002"].reasons
                if r.code == "GRAPH_DEVICE_CONFIRMED_LINK")
    assert code.attribution_pp == 0.0
    assert code.attribution_note == REDUNDANT_NOTE


def test_demo_2_group_counterfactual_collapses_the_score(explanations):
    e = explanations["ORD-DEMO-002"]
    assert e.p_abuse - e.p_abuse_without_graph_evidence >= DEMO_2_MIN_GRAPH_DROP


def test_demo_2_counterfactual_is_below_the_documented_marker(explanations):
    """§11 talking point: 'without relationship evidence: 10 %'."""
    assert explanations["ORD-DEMO-002"].p_abuse_without_graph_evidence < 0.30


# -- Demo 3: uncertain middle ------------------------------------------------
def test_demo_3_fires_the_claim_code(explanations):
    assert "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM" in _codes(explanations["ORD-DEMO-003"])


def test_demo_3_fires_a_device_code(explanations):
    assert [c for c in _codes(explanations["ORD-DEMO-003"]) if "DEVICE" in c]


# -- text safety, all three --------------------------------------------------
FEATURE_NAMES = tuple(set(definitions.ABUSE_FEATURES) | set(definitions.RETURN_FEATURES))


def _all_text(explanation):
    return " ".join([explanation.prediction_explanation]
                    + [r.reviewer_text for r in explanation.reasons]
                    + [r.reviewer_text for r in explanation.mitigating_reasons]
                    + [r.attribution_note or "" for r in explanation.reasons])


@pytest.mark.parametrize("order_id", ["ORD-DEMO-001", "ORD-DEMO-002", "ORD-DEMO-003"])
def test_text_contains_no_raw_feature_names(explanations, order_id):
    text = _all_text(explanations[order_id])
    assert not [f for f in FEATURE_NAMES if f in text]


@pytest.mark.parametrize("order_id", ["ORD-DEMO-001", "ORD-DEMO-002", "ORD-DEMO-003"])
def test_text_contains_no_guardrail_thresholds(explanations, order_id):
    """Config numbers are policy, not evidence, and must never reach a reviewer through a reason code.

    Bare counts (a "2" inside "2 accounts") are legitimate evidence, so this checks the thresholds as
    they would actually be rendered rather than every digit.
    """
    g = load_policy_config().guardrails
    rendered = {f"{g.block_min_p_abuse:.2f}", f"{g.high_exposure_min_p_abuse:.2f}",
                str(int(g.high_exposure_value_inr)), f"{int(g.high_exposure_value_inr):,}",
                str(int(g.degraded_review_min_value_inr)), f"{int(g.degraded_review_min_value_inr):,}"}
    text = _all_text(explanations[order_id])
    assert not [t for t in rendered if t in text]


@pytest.mark.parametrize("order_id", ["ORD-DEMO-001", "ORD-DEMO-002", "ORD-DEMO-003"])
def test_text_contains_no_model_version(explanations, bundles, order_id):
    text = _all_text(explanations[order_id])
    versions = [b["model_version"] for b in bundles.values()] + [b["feature_set_version"] for b in bundles.values()]
    assert not [v for v in versions if v in text]


@pytest.mark.parametrize("order_id", ["ORD-DEMO-001", "ORD-DEMO-002", "ORD-DEMO-003"])
def test_every_template_placeholder_was_filled(explanations, order_id):
    text = _all_text(explanations[order_id])
    assert "{" not in text and "}" not in text


# -- determinism through the whole path --------------------------------------
def test_explanations_are_reproducible(world, bundles):
    reference = registry.load_reference(bundles)
    builder = FeatureBuilder.replay(world, DEMO_CLOCK)
    request = ScoreOrderRequest.model_validate(
        next(p for p in D.demo_requests() if p["order_id"] == "ORD-DEMO-002"))
    features = builder.features_for_request(request, T0)
    links = builder.discounted_links(request, T0)
    first = explain_order(bundles, reference, features, links)
    second = explain_order(bundles, reference, features, links)
    assert first == second
