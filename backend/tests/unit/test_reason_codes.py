"""Reason codes as evidence statements (§6.5 as amended by #27), plus catalog and purity checks.

The rule under test throughout: the predicate decides whether a code fires; attribution only decides
what the code reports about itself.
"""
import ast
from pathlib import Path

import pytest

from sentinel.api.schemas import ReasonCode
from sentinel.features import definitions
from sentinel.models import reason_codes as rc
from sentinel.models.explain import (DOMINANCE_MIN_PP, NO_EVIDENCE_GROUP, PREDICTION_TEMPLATES,
                                     dominant_group, explanation_group, prediction_explanation,
                                     sort_by_attribution, sort_reasons)


@pytest.fixture(scope="module")
def catalog():
    return rc.load_catalog()


def _zero_features() -> dict:
    """Every feature at a value that trips no predicate."""
    values = {name: 0.0 for name in definitions.all_features()}
    values["primary_category"] = "APPAREL"
    values["delivery_speed"] = "STANDARD"
    return values


def _evidence(**overrides) -> rc.Evidence:
    links = overrides.pop("discounted_links", ())
    return rc.Evidence(features={**_zero_features(), **overrides}, discounted_links=links)


# -- catalog -----------------------------------------------------------------
def test_catalog_keeps_every_documented_code(catalog):
    documented = {
        "GRAPH_DEVICE_CONFIRMED_LINK", "GRAPH_TOKEN_REUSE", "GRAPH_COMMUNITY_RISK", "TEMPORAL_BURST",
        "SAME_SKU_COORDINATION", "ACCOUNT_PRIOR_SUSPICIOUS_CLAIM", "NEW_ACCOUNT_HIGH_VALUE",
        "MITIGATING_ESTABLISHED_ACCOUNT", "MITIGATING_DISCOUNTED_LINKS", "RETURN_SIZE_BRACKETING",
        "RETURN_HIGH_HISTORY",
    }
    assert documented <= set(catalog), sorted(documented - set(catalog))


def test_every_code_has_an_evidence_mapping(catalog):
    assert set(catalog) <= set(rc.CODE_FEATURES)


def test_catalog_is_missing_field_safe(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[meta]\nversion = "x"\n[codes.BROKEN]\nmodel = "ABUSE"\n', encoding="utf-8")
    with pytest.raises(rc.CatalogError, match="missing"):
        rc.load_catalog(path)


# -- predicate evaluation ----------------------------------------------------
def test_predicate_rejects_arbitrary_expressions():
    spec = rc.CodeSpec("X", "ABUSE", "INCREASES", "__import__('os').system('echo')", "t", "WEAK", 2.0)
    with pytest.raises(rc.CatalogError):
        rc.fires(spec, _evidence())


def test_predicate_rejects_unknown_names():
    spec = rc.CodeSpec("X", "ABUSE", "INCREASES", "nonexistent_feature >= 1", "t", "WEAK", 2.0)
    with pytest.raises(rc.CatalogError, match="nonexistent_feature"):
        rc.fires(spec, _evidence())


# -- firing rules (#27) ------------------------------------------------------
def test_no_code_fires_when_no_predicate_holds(catalog):
    increases, mitigating = rc.fired_codes(_evidence(), {"ABUSE": {}, "RETURN": {}}, catalog)
    assert increases == [] and mitigating == []


@pytest.mark.parametrize("code,features", [
    ("GRAPH_DEVICE_CONFIRMED_LINK", {"device_confirmed_abuse_weight": 0.3}),
    ("GRAPH_DEVICE_SHARED", {"device_other_accounts_30d": 3}),
    ("GRAPH_TOKEN_REUSE", {"token_other_accounts_30d": 2}),
    ("TEMPORAL_BURST", {"linked_orders_24h": 3}),
    ("SAME_SKU_COORDINATION", {"linked_same_sku_7d": 2}),
    ("ACCOUNT_PRIOR_SUSPICIOUS_CLAIM", {"prior_suspicious_claims_180d": 1}),
])
def test_code_fires_exactly_at_its_threshold(catalog, code, features):
    fired, _ = rc.fired_codes(_evidence(**features), {"ABUSE": {}, "RETURN": {}}, catalog)
    assert code in {f.code for f in fired}


@pytest.mark.parametrize("code,features", [
    ("GRAPH_DEVICE_CONFIRMED_LINK", {"device_confirmed_abuse_weight": 0.29}),
    ("GRAPH_DEVICE_SHARED", {"device_other_accounts_30d": 2}),
    ("GRAPH_TOKEN_REUSE", {"token_other_accounts_30d": 1}),
    ("TEMPORAL_BURST", {"linked_orders_24h": 2}),
    ("SAME_SKU_COORDINATION", {"linked_same_sku_7d": 1}),
    ("ACCOUNT_PRIOR_SUSPICIOUS_CLAIM", {"prior_suspicious_claims_180d": 0}),
])
def test_code_does_not_fire_below_its_threshold(catalog, code, features):
    fired, _ = rc.fired_codes(_evidence(**features), {"ABUSE": {}, "RETURN": {}}, catalog)
    assert code not in {f.code for f in fired}


def test_zero_attribution_does_not_suppress_a_fired_code(catalog):
    """The #27 behaviour: real evidence stays visible even when the model gave it no split."""
    evidence = _evidence(device_confirmed_abuse_weight=2.235)
    fired, _ = rc.fired_codes(evidence, {"ABUSE": {"device_confirmed_abuse_weight": 0.0}, "RETURN": {}},
                              catalog)
    code = next(f for f in fired if f.code == "GRAPH_DEVICE_CONFIRMED_LINK")
    assert code.attribution_pp == 0.0
    assert code.attribution_note == rc.REDUNDANT_NOTE


def test_strong_attribution_carries_no_note(catalog):
    evidence = _evidence(device_confirmed_abuse_weight=2.235)
    fired, _ = rc.fired_codes(evidence, {"ABUSE": {"device_confirmed_abuse_weight": 30.0}, "RETURN": {}},
                              catalog)
    code = next(f for f in fired if f.code == "GRAPH_DEVICE_CONFIRMED_LINK")
    assert code.attribution_note is None


def test_note_threshold_is_exclusive(catalog):
    evidence = _evidence(device_confirmed_abuse_weight=2.235)
    at = rc.REDUNDANT_ATTRIBUTION_PP
    for value, expected in ((at, None), (at - 0.001, rc.REDUNDANT_NOTE), (-at, None)):
        fired, _ = rc.fired_codes(evidence, {"ABUSE": {"device_confirmed_abuse_weight": value},
                                             "RETURN": {}}, catalog)
        code = next(f for f in fired if f.code == "GRAPH_DEVICE_CONFIRMED_LINK")
        assert code.attribution_note == expected, value


def test_mitigating_codes_are_returned_separately(catalog):
    evidence = _evidence(account_age_days=400, prior_orders=12, prior_suspicious_claims_180d=0)
    increases, mitigating = rc.fired_codes(evidence, {"ABUSE": {}, "RETURN": {}}, catalog)
    assert "MITIGATING_ESTABLISHED_ACCOUNT" in {m.code for m in mitigating}
    assert "MITIGATING_ESTABLISHED_ACCOUNT" not in {i.code for i in increases}
    assert all(m.direction == "DECREASES" for m in mitigating)
    assert all(i.direction == "INCREASES" for i in increases)


# -- rendered text -----------------------------------------------------------
def test_rendering_is_deterministic(catalog):
    evidence = _evidence(token_other_accounts_30d=3)
    a, _ = rc.fired_codes(evidence, {"ABUSE": {}, "RETURN": {}}, catalog)
    b, _ = rc.fired_codes(evidence, {"ABUSE": {}, "RETURN": {}}, catalog)
    assert [x.reviewer_text for x in a] == [x.reviewer_text for x in b]


def test_component_confirmed_count_inverts_the_smoothing():
    features = {"component_size_reliable_90d": 8, "component_abuse_ratio_smoothed": (3 + 1) / (8 + 10)}
    assert rc.component_confirmed_accounts(features) == 3


def test_device_code_without_counts_uses_the_counts_free_wording(catalog):
    evidence = _evidence(device_confirmed_abuse_weight=1.0)
    fired, _ = rc.fired_codes(evidence, {"ABUSE": {}, "RETURN": {}}, catalog)
    code = next(f for f in fired if f.code == "GRAPH_DEVICE_CONFIRMED_LINK")
    assert "{" not in code.reviewer_text
    assert code.reviewer_text == catalog["GRAPH_DEVICE_CONFIRMED_LINK"].template_unconfirmed_counts


def _device_code(catalog, accounts, days):
    evidence = rc.Evidence(features={**_zero_features(), "device_confirmed_abuse_weight": 1.0},
                           device_confirmed_accounts=accounts, device_last_confirmed_days=days)
    fired, _ = rc.fired_codes(evidence, {"ABUSE": {}, "RETURN": {}}, catalog)
    return next(f for f in fired if f.code == "GRAPH_DEVICE_CONFIRMED_LINK")


def test_device_code_uses_the_documented_wording_once_counts_exist(catalog):
    text = _device_code(catalog, 3, 5.0).reviewer_text
    assert text == "This device was used by 3 accounts later confirmed for return abuse, most recently 5 days ago."


def test_device_code_days_are_whole_days_elapsed(catalog):
    """3.75 days reads "3 days ago": never rounded up to a day that has not yet passed."""
    code = _device_code(catalog, 3, 3.75)
    assert code.reviewer_text.endswith("most recently 3 days ago.")
    assert code.evidence["days_since_confirmation"] == 3


def test_device_code_singular_forms(catalog):
    text = _device_code(catalog, 1, 1.2).reviewer_text
    assert text == "This device was used by 1 account later confirmed for return abuse, most recently 1 day ago."


def test_device_code_with_only_one_value_falls_back(catalog):
    code = _device_code(catalog, 3, None)
    assert code.reviewer_text == catalog["GRAPH_DEVICE_CONFIRMED_LINK"].template_unconfirmed_counts


# -- count-aware rendering ----------------------------------------------------
def test_fill_chooses_singular_only_for_exactly_one():
    template = "{n} {n:claim|claims}"
    assert [rc.fill(template, {"n": n}) for n in (0, 1, 2)] == ["0 claims", "1 claim", "2 claims"]


def test_fill_rejects_an_unknown_plural_name():
    with pytest.raises(rc.CatalogError, match="missing_name"):
        rc.fill("{missing_name:a|b}", {"n": 1})


def test_no_template_uses_a_parenthesised_plural(catalog):
    for spec in catalog.values():
        for text in (spec.template, spec.template_unconfirmed_counts, spec.template_without_counts):
            assert "(s)" not in (text or ""), spec.code


@pytest.mark.parametrize("code,feature,value,expected", [
    ("ACCOUNT_PRIOR_SUSPICIOUS_CLAIM", "prior_suspicious_claims_180d", 1,
     "The account had 1 flagged return or delivery claim in the last 6 months."),
    ("ACCOUNT_PRIOR_SUSPICIOUS_CLAIM", "prior_suspicious_claims_180d", 2,
     "The account had 2 flagged return or delivery claims in the last 6 months."),
    ("GRAPH_TOKEN_REUSE", "token_other_accounts_30d", 2,
     "The payment method was used by 2 other accounts in the last 30 days."),
    ("GRAPH_DEVICE_SHARED", "device_other_accounts_30d", 3,
     "This device was used by 3 other accounts in the last 30 days."),
    ("TEMPORAL_BURST", "linked_orders_24h", 4, "Linked accounts placed 4 orders in the last 24 hours."),
    ("SAME_SKU_COORDINATION", "linked_same_sku_7d", 2, "Linked accounts ordered the same item 2 times this week."),
])
def test_count_templates_render_plain_english(catalog, code, feature, value, expected):
    fired, _ = rc.fired_codes(_evidence(**{feature: value}), {"ABUSE": {}, "RETURN": {}}, catalog)
    assert next(f for f in fired if f.code == code).reviewer_text == expected


def test_temporal_burst_counts_orders_not_accounts(catalog):
    """1.2: linked_orders_24h counts orders, so the sentence must say orders."""
    fired, _ = rc.fired_codes(_evidence(linked_orders_24h=4), {"ABUSE": {}, "RETURN": {}}, catalog)
    text = next(f for f in fired if f.code == "TEMPORAL_BURST").reviewer_text
    assert "4 orders" in text and "linked accounts placed orders" not in text.lower()


def _return_history(catalog, **counts):
    evidence = rc.Evidence(features={**_zero_features(), "matured_return_rate_smoothed": 0.5}, **counts)
    fired, _ = rc.fired_codes(evidence, {"ABUSE": {}, "RETURN": {}}, catalog)
    return next(f for f in fired if f.code == "RETURN_HIGH_HISTORY")


def test_return_history_renders_the_raw_matured_counts(catalog):
    code = _return_history(catalog, matured_returns=28, matured_orders=48)
    assert code.reviewer_text == ("The customer returned 28 of 48 delivered orders. "
                                  "This affects return likelihood, not abuse risk.")
    assert code.evidence == {"returns": 28, "matured_orders": 48}


def test_return_history_without_counts_states_no_number(catalog):
    code = _return_history(catalog)
    assert code.reviewer_text == catalog["RETURN_HIGH_HISTORY"].template_without_counts
    assert not any(ch.isdigit() for ch in code.reviewer_text)


def test_return_history_still_fires_on_the_smoothed_rate(catalog):
    """Only the text changed: a smoothed rate under 0.4 never fires, whatever the raw counts say."""
    evidence = rc.Evidence(features={**_zero_features(), "matured_return_rate_smoothed": 0.39},
                           matured_returns=9, matured_orders=10)
    fired, _ = rc.fired_codes(evidence, {"ABUSE": {}, "RETURN": {}}, catalog)
    assert "RETURN_HIGH_HISTORY" not in {f.code for f in fired}


def test_fired_codes_satisfy_the_api_contract(catalog):
    evidence = _evidence(device_confirmed_abuse_weight=2.235, token_other_accounts_30d=3)
    fired, _ = rc.fired_codes(evidence, {"ABUSE": {"device_confirmed_abuse_weight": 0.0}, "RETURN": {}},
                              catalog)
    for code in fired:
        model = ReasonCode.model_validate(vars(code))
        assert model.code == code.code and model.attribution_note == code.attribution_note


def test_attribution_note_is_optional_on_the_contract():
    """Existing payloads stay valid: the new field must not become required (#27)."""
    model = ReasonCode.model_validate({
        "code": "X", "model": "ABUSE", "direction": "INCREASES", "reviewer_text": "t",
        "evidence": {}, "attribution_pp": 1.0, "evidence_strength": "WEAK"})
    assert model.attribution_note is None


# -- prediction explanation --------------------------------------------------
def test_dominant_group_prefers_the_largest_delta():
    assert dominant_group({"graph": 5.0, "account": 40.0, "order": 1.0}) == "account"


def test_dominant_group_breaks_ties_by_precedence():
    assert dominant_group({"graph": 10.0, "account": 10.0, "order": 10.0}) == "graph"


def test_dominant_group_is_none_below_the_threshold():
    below = DOMINANCE_MIN_PP - 0.01
    assert dominant_group({"graph": below, "account": below, "order": below}) is None
    assert explanation_group({"graph": below}) == NO_EVIDENCE_GROUP


def test_prediction_explanation_is_one_of_the_templates():
    text = prediction_explanation({"graph": 50.0, "account": 1.0, "order": 0.0})
    assert text == PREDICTION_TEMPLATES["graph"]


def test_reasons_sort_by_evidence_strength_first(catalog):
    """1.1: a WEAK code never outranks STRONG or MODERATE evidence, however large its attribution."""
    codes = [rc.FiredCode("W", "ABUSE", "INCREASES", "", {}, 94.0, "WEAK"),
             rc.FiredCode("M", "ABUSE", "INCREASES", "", {}, 4.0, "MODERATE"),
             rc.FiredCode("S", "ABUSE", "INCREASES", "", {}, 0.0, "STRONG")]
    assert [c.code for c in sort_reasons(codes, list(catalog))] == ["S", "M", "W"]


def test_reasons_within_a_strength_sort_by_absolute_attribution_then_catalog_order(catalog):
    order = list(catalog)
    codes = [rc.FiredCode("A", "ABUSE", "INCREASES", "", {}, 1.0, "WEAK"),
             rc.FiredCode("B", "ABUSE", "INCREASES", "", {}, -30.0, "WEAK"),
             rc.FiredCode("C", "ABUSE", "INCREASES", "", {}, None, "WEAK")]
    assert [c.code for c in sort_reasons(codes, order)] == ["B", "A", "C"]


def test_strength_and_attribution_ties_fall_back_to_catalog_order(catalog):
    first, second = list(catalog)[:2]
    codes = [rc.FiredCode(second, "ABUSE", "INCREASES", "", {}, 5.0, "STRONG"),
             rc.FiredCode(first, "ABUSE", "INCREASES", "", {}, -5.0, "STRONG")]
    assert [c.code for c in sort_reasons(codes, list(catalog))] == [first, second]


def test_attribution_view_sorts_by_magnitude_only(catalog):
    codes = [rc.FiredCode("S", "ABUSE", "INCREASES", "", {}, 0.0, "STRONG"),
             rc.FiredCode("W", "ABUSE", "INCREASES", "", {}, 94.0, "WEAK"),
             rc.FiredCode("M", "ABUSE", "INCREASES", "", {}, -4.0, "MODERATE")]
    assert [c.code for c in sort_by_attribution(codes, list(catalog))] == ["W", "M", "S"]


# -- purity ------------------------------------------------------------------
MODELS_DIR = Path(rc.__file__).resolve().parent
ACTION_NAMES = ("ALLOW", "PREPAID_ONLY", "MANUAL_REVIEW", "BLOCK")


def _module_files():
    return sorted(MODELS_DIR.rglob("*.py"))


def test_models_never_import_policy():
    for path in _module_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not [n for n in names if n and n.startswith("sentinel.policy")], path


def test_models_never_name_an_action():
    for path in _module_files():
        text = path.read_text(encoding="utf-8")
        assert not [a for a in ACTION_NAMES if a in text], path
