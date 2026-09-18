"""§11 demo explanations through the committed artifacts and the real FeatureBuilder (§6.5, #27).

Nothing here sets a probability: every number comes from the committed models scoring the real demo
feature rows. The assertions are about which evidence is reported and how, not about the score.
"""
import pytest

from sentinel.api.schemas import ScoreOrderRequest
from sentinel.data import demo_orders as D
from sentinel.features import definitions
from sentinel.features.builder import FeatureBuilder
from sentinel.features.graph_state import to_micros
from sentinel.features.tabular_features import matured_return_counts
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


def _explain(builder, bundles, reference, request):
    """The serving path's evidence: device confirmation counts (#28) and raw matured return counts."""
    evidence = builder.evidence_values(request, T0)
    returns, matured = matured_return_counts(builder.state, request.account_id, to_micros(T0))
    return explain_order(bundles, reference, builder.features_for_request(request, T0),
                         builder.discounted_links(request, T0),
                         device_confirmed_accounts=evidence["device_confirmed_peer_count"],
                         device_last_confirmed_days=evidence["device_most_recent_confirmation_days"],
                         matured_returns=returns, matured_orders=matured)


@pytest.fixture(scope="module")
def explanations(world, bundles):
    reference = registry.load_reference(bundles)
    builder = FeatureBuilder.replay(world, DEMO_CLOCK)
    out = {}
    for payload in D.demo_requests():
        request = ScoreOrderRequest.model_validate(payload)
        out[request.order_id] = _explain(builder, bundles, reference, request)
    return out


def _text(explanation, code):
    return next(r.reviewer_text for r in explanation.reasons + explanation.mitigating_reasons if r.code == code)


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


def test_demo_1_return_history_states_the_raw_counts(world, explanations):
    """1.4: the sentence reports the account's actual matured returns, not the smoothed model input."""
    code = next(r for r in explanations["ORD-DEMO-001"].reasons if r.code == "RETURN_HIGH_HISTORY")
    returns, matured = code.evidence["returns"], code.evidence["matured_orders"]
    assert 0 < returns < matured
    assert code.reviewer_text == (f"The customer returned {returns} of {matured} delivered orders. "
                                  "This affects return likelihood, not abuse risk.")
    assert "%" not in code.reviewer_text


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


def test_demo_2_device_code_states_the_confirmed_counts(explanations):
    """1.6 / #28: three peers confirmed, the latest 3.7 days before t0, rendered in whole days."""
    code = next(r for r in explanations["ORD-DEMO-002"].reasons if r.code == "GRAPH_DEVICE_CONFIRMED_LINK")
    assert code.evidence["confirmed_accounts"] == 3
    days = code.evidence["days_since_confirmation"]
    assert code.reviewer_text == ("This device was used by 3 accounts later confirmed for return abuse, "
                                  f"most recently {days} days ago.")


def test_demo_2_burst_counts_orders(explanations):
    assert _text(explanations["ORD-DEMO-002"], "TEMPORAL_BURST") == \
        "Linked accounts placed 4 orders in the last 24 hours."


def test_demo_2_strong_evidence_leads_the_reasons(explanations):
    """1.1: the top reason for a ring member is the STRONG device or token evidence, not the WEAK
    new-account code, even though the WEAK code has the largest attribution."""
    e = explanations["ORD-DEMO-002"]
    order = ("STRONG", "MODERATE", "WEAK")
    strengths = [r.evidence_strength for r in e.reasons]
    assert strengths == sorted(strengths, key=order.index)
    assert e.reasons[0].evidence_strength == "STRONG"
    assert e.reasons[-1].code == "NEW_ACCOUNT_HIGH_VALUE"


def test_demo_2_attribution_view_keeps_the_same_codes_by_magnitude(explanations):
    e = explanations["ORD-DEMO-002"]
    assert {r.code for r in e.attributions_by_magnitude} == {r.code for r in e.reasons}
    magnitudes = [abs(r.attribution_pp or 0.0) for r in e.attributions_by_magnitude]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert e.attributions_by_magnitude[0].code == "NEW_ACCOUNT_HIGH_VALUE"


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


def test_demo_3_claim_text_is_singular(explanations):
    """1.3: exactly the sentence the brief requires."""
    assert _text(explanations["ORD-DEMO-003"], "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM") == \
        "The account had 1 flagged return or delivery claim in the last 6 months."


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


@pytest.mark.parametrize("order_id", ["ORD-DEMO-001", "ORD-DEMO-002", "ORD-DEMO-003"])
def test_text_has_no_parenthesised_plurals_or_wrong_number(explanations, order_id):
    """1.3: count-aware rendering everywhere; "1 ... claims" or "(s)" never reaches a reviewer."""
    import re
    text = _all_text(explanations[order_id])
    assert "(s)" not in text
    assert not re.search(r"\b1 (accounts|orders|claims|days|times)\b", text)


# -- determinism through the whole path --------------------------------------
def test_explanations_are_reproducible(world, bundles):
    reference = registry.load_reference(bundles)
    builder = FeatureBuilder.replay(world, DEMO_CLOCK)
    request = ScoreOrderRequest.model_validate(
        next(p for p in D.demo_requests() if p["order_id"] == "ORD-DEMO-002"))
    assert _explain(builder, bundles, reference, request) == _explain(builder, bundles, reference, request)
