"""§6.5 ablation attributions: determinism, the group counterfactual, reference integrity and latency.

These run against the committed artifacts and the committed reference vector, not a retrained model.
"""
import json
import time

import pytest

from sentinel.features.definitions import ABUSE_GRAPH_FEATURES
from sentinel.models import registry
from sentinel.models.attribution import ablation, attributions, group_attribution
from sentinel.models.reason_codes import GROUPS

# Both models plus the group call, per order. Asserted on the median and the p95 of a warmed loop: a single
# timing on a shared machine measures scheduler noise, not the code; p95 bounds the per-request tail.
LATENCY_BUDGET_MS = 20.0
LATENCY_P95_BUDGET_MS = 40.0
LATENCY_RUNS = 60


@pytest.fixture(scope="module")
def bundles():
    return {name: registry.load_bundle(name) for name in registry.MODEL_NAMES}


@pytest.fixture(scope="module")
def reference(bundles):
    return registry.load_reference(bundles)


@pytest.fixture(scope="module")
def row(reference):
    """A plausible order built from the reference itself, so the test needs no world replay."""
    values = dict(reference["values"])
    values.update(order_value_inr=24000.0, account_age_days=6.0, prior_orders=0.0,
                  device_other_accounts_30d=5.0, device_confirmed_abuse_weight=2.235,
                  token_other_accounts_30d=3.0, linked_orders_24h=4.0, linked_same_sku_7d=3.0,
                  component_size_reliable_90d=8.0, component_abuse_ratio_smoothed=0.2222)
    return values


# -- determinism -------------------------------------------------------------
def test_attributions_are_deterministic(bundles, reference, row):
    assert attributions(bundles["abuse"], reference, row) == attributions(bundles["abuse"], reference, row)


def test_group_attribution_is_deterministic(bundles, reference, row):
    first = group_attribution(bundles["abuse"], reference, row, ABUSE_GRAPH_FEATURES)
    assert first == group_attribution(bundles["abuse"], reference, row, ABUSE_GRAPH_FEATURES)


def test_baseline_matches_the_ordinary_predict_path(bundles, reference, row):
    """The ablation's baseline row must be the same probability the scoring path would produce."""
    import pandas as pd

    from sentinel.models.train import predict
    assert ablation(bundles["abuse"], reference, row).p == pytest.approx(
        float(predict(bundles["abuse"], pd.DataFrame([row]))[0]), rel=1e-12)


# -- shape and meaning -------------------------------------------------------
def test_one_delta_per_model_feature(bundles, reference, row):
    deltas = attributions(bundles["abuse"], reference, row)
    assert set(deltas) == set(bundles["abuse"]["feature_list"])


def test_a_feature_already_at_reference_has_zero_delta(bundles, reference, row):
    at_reference = {**row, "linked_orders_24h": reference["values"]["linked_orders_24h"]}
    assert attributions(bundles["abuse"], reference, at_reference)["linked_orders_24h"] == 0.0


def test_group_ablation_is_not_the_sum_of_its_members(bundles, reference, row):
    """Deltas are not additive; the module must not imply otherwise (§6.5)."""
    result = ablation(bundles["abuse"], reference, row, {"graph": ABUSE_GRAPH_FEATURES})
    total = sum(result.deltas[f] for f in ABUSE_GRAPH_FEATURES)
    assert result.group_delta_pp["graph"] != pytest.approx(total, abs=1e-6)


def test_attribution_module_exposes_no_summing_helper():
    from sentinel.models import attribution
    assert not [n for n in dir(attribution) if "sum" in n.lower() or "total" in n.lower()]


def test_missing_reference_value_is_an_error(bundles, reference, row):
    broken = {"values": {k: v for k, v in reference["values"].items() if k != "linked_orders_24h"}}
    with pytest.raises(KeyError, match="linked_orders_24h"):
        attributions(bundles["abuse"], broken, row)


# -- reference integrity -----------------------------------------------------
def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_tampered_reference_raises(bundles, reference, tmp_path):
    payload = dict(reference)
    payload["values"] = {**payload["values"], "order_value_inr": 999999.0}   # sha256 no longer matches
    _write(registry.reference_path(tmp_path), payload)
    with pytest.raises(registry.ReferenceError, match="SHA-256 mismatch"):
        registry.load_reference(bundles, tmp_path)


def test_feature_set_version_mismatch_raises(bundles, reference, tmp_path):
    payload = dict(reference, feature_set_version="fs-1.0-deadbeef")
    payload["sha256"] = registry._reference_digest(payload)                  # honestly re-signed
    _write(registry.reference_path(tmp_path), payload)
    with pytest.raises(registry.ReferenceError, match="feature set"):
        registry.load_reference(bundles, tmp_path)


def test_model_version_mismatch_raises(bundles, reference, tmp_path):
    payload = dict(reference, model_versions={**reference["model_versions"], "abuse": "abuse-hgb-fs1.0-00000000"})
    payload["sha256"] = registry._reference_digest(payload)
    _write(registry.reference_path(tmp_path), payload)
    with pytest.raises(registry.ReferenceError, match="abuse model"):
        registry.load_reference(bundles, tmp_path)


def test_missing_reference_file_raises(bundles, tmp_path):
    with pytest.raises(registry.ReferenceError, match="not found"):
        registry.load_reference(bundles, tmp_path)


def test_committed_reference_was_built_from_genuine_calibration_rows(reference):
    assert reference["split"] == "CALIBRATION" and reference["label_filter"] == "abuse_label == 0"
    assert reference["rows"] > 0


# -- latency -----------------------------------------------------------------
def test_attribution_latency_budget(bundles, reference, row):
    def one_order():
        ablation(bundles["abuse"], reference, row, GROUPS)
        ablation(bundles["return"], reference, row)

    for _ in range(5):
        one_order()
    timings = []
    for _ in range(LATENCY_RUNS):
        start = time.perf_counter()
        one_order()
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    median = timings[len(timings) // 2]
    p95 = timings[int(0.95 * (len(timings) - 1))]
    assert len(timings) >= 50
    assert median < LATENCY_BUDGET_MS, f"median {median:.2f} ms over budget {LATENCY_BUDGET_MS} ms"
    assert p95 < LATENCY_P95_BUDGET_MS, f"p95 {p95:.2f} ms over budget {LATENCY_P95_BUDGET_MS} ms"


def test_one_predict_per_model(bundles, reference, row, monkeypatch):
    """The budget depends on batching: one model call per model per order, never one per feature."""
    calls = []
    original = bundles["abuse"]["base_model"].predict_proba
    monkeypatch.setattr(bundles["abuse"]["base_model"], "predict_proba",
                        lambda X: (calls.append(len(X)), original(X))[1])
    ablation(bundles["abuse"], reference, row, GROUPS)
    assert len(calls) == 1
    assert calls[0] == 1 + len(bundles["abuse"]["feature_list"]) + len(GROUPS)
