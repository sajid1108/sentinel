"""Phase 4 checkpoint: split hygiene, calibration isolation, determinism, model sanity and backtest (§6.4, §7.2
P8, P9, P13, §13.3). Everything is recomputed from the seeded world; metrics use the committed artifacts."""
import os
import warnings

import numpy as np
import pandas as pd
import pytest

from sentinel.evaluation import backtest as B
from sentinel.evaluation.cohorts import HARD_NEGATIVE_ARCHETYPES
from sentinel.evaluation.report import run_evaluation
from sentinel.evaluation.splits import offline_data
from sentinel.features.builder import EVIDENCE_COLUMNS, POLICY_INPUT_COLUMNS, WORLD_TABLES, build_tables
from sentinel.models import registry
from sentinel.models.train import CALIBRATION, MODEL_SPECS, TEST, TRAIN, base_scores, labelled_rows, predict, \
    train_all, train_model
from sentinel.policy.config import load_policy_config
from sentinel.settings import DEMO_CLOCK

pytestmark = pytest.mark.slow


@pytest.fixture(scope="session")
def tables(world):
    return build_tables({t: world[t] for t in WORLD_TABLES})


@pytest.fixture(scope="session")
def offline(world, tables):
    features, policy = tables
    return offline_data(features, policy, world["order_labels"], world["orders"], world["sim_ground_truth"])


@pytest.fixture(scope="session")
def trained(offline):
    return train_all(offline.frame, DEMO_CLOCK)


@pytest.fixture(scope="session")
def committed():
    return {name: registry.load_bundle(name) for name in registry.MODEL_NAMES}


@pytest.fixture(scope="session")
def evaluation(offline, committed):
    return run_evaluation(offline, committed, load_policy_config())


def _ids(frame: pd.DataFrame, split: str) -> set[str]:
    return set(frame.loc[frame["split"] == split, "order_id"])


# ── policy inputs table ──────────────────────────────────────────────────────
def test_policy_inputs_table(world, tables):
    features, policy = tables
    assert list(policy.columns) == ["order_id", "split", "t0", *POLICY_INPUT_COLUMNS, *EVIDENCE_COLUMNS]
    assert (policy["order_id"] == features["order_id"]).all() and (policy["graph_state_as_of"] == policy["t0"]).all()
    assert (policy["order_value_inr"] == features["order_value_inr"]).all()
    rate = policy["matured_return_rate"]
    assert (policy.loc[rate.isna(), "matured_returns"] == 0).all() and rate.dropna().between(0, 1).all()
    assert (policy["clv_inr"] >= 2000).all()


# ── split hygiene (P8, P9, P13) ──────────────────────────────────────────────
def test_split_hygiene(world, offline, trained, evaluation):
    report, prov = evaluation
    frame = offline.frame
    train_ids, calib_ids, test_ids = _ids(frame, TRAIN), _ids(frame, CALIBRATION), _ids(frame, TEST)
    assert not (train_ids & calib_ids) and not (train_ids & test_ids) and not (calib_ids & test_ids)
    used = []
    for result in trained.values():
        assert set(result.train_order_ids) <= train_ids
        assert set(result.calibration_order_ids) <= calib_ids
        used += [result.train_order_ids, result.calibration_order_ids]
    assert set(prov.no_graph_train_rows) <= train_ids and set(prov.no_graph_calibration_rows) <= calib_ids
    for rows in prov.model_metric_rows.values():
        assert set(rows) <= test_ids
        used.append(rows)
    assert set(prov.backtest_rows) <= test_ids
    assert set(prov.tuning_rows) <= calib_ids                                   # P13
    used += [prov.backtest_rows, prov.tuning_rows]

    demo_accounts = set(world["sim_ground_truth"].query("archetype == 'DEMO'")["account_id"])
    demo_orders = set(world["orders"].loc[world["orders"]["account_id"].isin(demo_accounts), "order_id"])
    assert len(demo_orders) == 59
    assert not demo_orders & set().union(*map(set, used))
    for result in trained.values():                                             # NULL labels excluded
        spec = MODEL_SPECS[result.bundle["name"]]
        labelled = frame.set_index("order_id")[spec.label]
        assert labelled.loc[list(result.train_order_ids)].notna().all()
    assert report["backtest_details"]["rows"]["fixed_threshold_tuning_calibration"]["rows"] == len(prov.tuning_rows)


def test_committed_bundles_record_their_windows(committed, trained):
    for name, bundle in committed.items():
        assert bundle["train_window"] == trained[name].bundle["train_window"]
        assert bundle["train_window"]["split"] == TRAIN and bundle["calibration_window"]["split"] == CALIBRATION
        assert bundle["trained_at"] == DEMO_CLOCK.isoformat()


# ── calibration uses CALIBRATION only (P9) ───────────────────────────────────
def test_calibration_fit_uses_calibration_rows_only(offline):
    spec = MODEL_SPECS["abuse"]
    frame = offline.frame
    base = train_model(spec, frame, DEMO_CLOCK)
    tampered = frame.copy()
    calib = tampered["split"] == CALIBRATION
    tampered.loc[calib, "abuse_label"] = 1 - tampered.loc[calib, "abuse_label"]
    flipped = train_model(spec, tampered, DEMO_CLOCK)

    test_rows = labelled_rows(frame, TEST, spec.label)
    train_rows = labelled_rows(frame, TRAIN, spec.label)
    assert not np.allclose(predict(base.bundle, test_rows), predict(flipped.bundle, test_rows))
    assert np.array_equal(base_scores(base.bundle, train_rows), base_scores(flipped.bundle, train_rows))


def test_labels_outside_train_and_calibration_do_not_change_the_model(offline):
    spec = MODEL_SPECS["return"]
    frame = offline.frame
    tampered = frame.copy()
    other = ~tampered["split"].isin([TRAIN, CALIBRATION])
    tampered.loc[other, "return_label"] = 1 - tampered.loc[other, "return_label"]
    rows = labelled_rows(frame, TEST, spec.label)
    assert np.array_equal(predict(train_model(spec, frame, DEMO_CLOCK).bundle, rows),
                          predict(train_model(spec, tampered, DEMO_CLOCK).bundle, rows))


# ── determinism ──────────────────────────────────────────────────────────────
def test_training_twice_gives_identical_artifacts(offline, tmp_path):
    shas = []
    for run in ("a", "b"):
        results = train_all(offline.frame, DEMO_CLOCK)
        reg = registry.save_bundles({n: r.bundle for n, r in results.items()}, tmp_path / run)
        shas.append({n: e["sha256"] for n, e in reg["models"].items()})
    assert shas[0] == shas[1]


def test_committed_artifacts_reproduce_on_the_same_cpu_count(offline, tmp_path):
    reg = registry.load_registry()
    if reg.get("cpu_count") != os.cpu_count():
        pytest.skip("different cpu_count; committed hash not comparable")
    results = train_all(offline.frame, DEMO_CLOCK)
    fresh = registry.save_bundles({n: r.bundle for n, r in results.items()}, tmp_path)
    assert {n: e["sha256"] for n, e in fresh["models"].items()} == \
        {n: e["sha256"] for n, e in reg["models"].items()}, "committed artifacts do not reproduce from the seeded world"


# ── model sanity (§13.3) ─────────────────────────────────────────────────────
def _model(report, name):
    return next(m for m in report["models"] if m["model"] == name)


def test_abuse_pr_auc_in_range(evaluation):
    assert 0.45 <= _model(evaluation[0], "ABUSE")["pr_auc"] <= 0.95


def test_return_pr_auc_beats_1_5_times_prevalence(evaluation):
    # review-bound correction (#25): the return model does not drive actions (G1)
    report = evaluation[0]
    prevalence = report["model_details"]["RETURN"]["test"]["prevalence"]
    assert _model(report, "RETURN")["pr_auc"] > 1.5 * prevalence


def test_abuse_ece_warning_only(evaluation):
    report = evaluation[0]
    ece = _model(report, "ABUSE")["ece_10bin_quantile"]
    assert report["model_details"]["ABUSE"]["ece_warning"] == (ece > 0.05)
    if ece > 0.05:
        warnings.warn(f"abuse TEST ECE {ece:.3f} > 0.05 (recorded in evaluation.json)")


def test_graph_uplift(evaluation):
    g = evaluation[0]["graph_uplift"]
    assert g["test_pr_auc_full"] - g["test_pr_auc_no_graph"] >= 0.10


def test_cold_start_ring_recall_full_beats_no_graph(evaluation):
    r3 = evaluation[0]["cold_start_ring_recall_detail"]
    assert r3["full"]["abusive_orders"] > 0
    assert r3["full"]["recall"] > r3["no_graph"]["recall"]


def test_frequent_returner_separation(evaluation):
    assert evaluation[0]["separation"]["pearson_p_return_p_abuse"] < 0.2


@pytest.mark.parametrize("archetype", HARD_NEGATIVE_ARCHETYPES)
def test_hard_negatives_not_blocked_more_than_normal(evaluation, archetype):
    by = evaluation[0]["backtest_details"]["by_archetype"]
    assert by[archetype]["genuine"] > 0
    assert by[archetype]["SENTINEL"]["genuine_block_rate"] <= by["NORMAL"]["SENTINEL"]["genuine_block_rate"] + 0.01


# ── report shape ─────────────────────────────────────────────────────────────
def test_report_matches_committed_file(evaluation):
    import json

    from sentinel.settings import ARTIFACTS_DIR

    committed = json.loads((ARTIFACTS_DIR / "reports" / "evaluation.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(evaluation[0], ensure_ascii=False)) == committed


def test_report_money_and_notice(evaluation):
    from sentinel.api.schemas import MetricsResponse, StrategyBacktest

    report = evaluation[0]
    assert report["data_notice"] == MetricsResponse.model_fields["data_notice"].annotation.__args__[0]
    assert [s["strategy"] for s in report["backtest"]] == list(B.STRATEGIES)
    for s in report["backtest"]:
        StrategyBacktest.model_validate(s)
    for variant in report["label_sensitivity"].values():
        assert len(variant["backtest"]) == 4
    assert len(report["sensitivity"]) == len(B.COST_GROUPS) * len(B.COST_FACTORS)


# ── monotonic constraints (Phase 4 decision B2) ──────────────────────────────
@pytest.mark.parametrize("name", ["abuse", "return"])
def test_calibrated_probability_is_monotone_in_constrained_features(offline, committed, name):
    spec = MODEL_SPECS[name]
    bundle = committed[name]
    assert bundle["monotonic_constraints"] == spec.monotonic_map()
    assert registry.load_registry()["models"][name]["monotonic_constraints"] == spec.monotonic_map()
    test_rows = labelled_rows(offline.frame, TEST, spec.label)
    sample = test_rows.sample(200, random_state=20260901)
    train_rows = labelled_rows(offline.frame, TRAIN, spec.label)
    for feature in spec.monotonic_increasing:
        lo, hi = np.percentile(train_rows[feature].astype(float), [1, 99])
        values = np.linspace(lo, hi, 6)
        grid = pd.concat([sample.assign(**{feature: v}) for v in values], ignore_index=True)
        p = predict(bundle, grid).reshape(len(values), len(sample))
        assert (np.diff(p, axis=0) >= -1e-9).all(), feature


def test_registry_records_cpu_count(committed):
    assert isinstance(registry.load_registry()["cpu_count"], int)


# ── confirmed-neighbour evidence reaches TRAIN (Phase 4 decision B1) ─────────
def test_train_positives_with_confirmed_neighbour_evidence(offline):
    """Data-health check only, bound >= 20 (architect decision 2.2). The behaviour it once proxied - that
    the trained model responds to this evidence - was measured directly and is false: both features get
    zero splits in the full model because correlated features identify the same rows first (#25)."""
    f = offline.frame
    positives = f[(f["split"] == TRAIN) & (f["abuse_label"] == 1)]
    evidence = (positives["device_confirmed_abuse_weight"] >= 0.3) | (positives["confirmed_abuse_proximity"] > 0)
    assert evidence.sum() >= 20


# ── new report sections (Phase 4 decisions D, E) ─────────────────────────────
def test_guardrail_cost_section(evaluation):
    g = evaluation[0]["guardrail_cost"]
    assert set(g["strategies"]) == {"SENTINEL", "SENTINEL_UNCONSTRAINED", "FIXED_THRESHOLD"}
    s, u = g["strategies"]["SENTINEL"], g["strategies"]["SENTINEL_UNCONSTRAINED"]
    effect = g["guardrail_effect"]
    assert effect["genuine_blocks_avoided"] == u["genuine_block"] - s["genuine_block"]
    extra = s["realized_cost_per_1000"]["inr"] - u["realized_cost_per_1000"]["inr"]
    assert effect["extra_realized_cost_per_1000"]["inr"] == pytest.approx(extra, abs=0.02)
    assert sum(v["orders"] for v in g["per_guardrail"].values()) >= effect["decisions_changed"]
    backtest = {b["strategy"]: b for b in evaluation[0]["backtest"]}
    assert s["realized_cost_per_1000"] == backtest["SENTINEL"]["realized_cost_per_1000"]


def test_calibration_bands_section(evaluation):
    bands = evaluation[0]["calibration_bands"]
    for model in ("ABUSE", "RETURN"):
        for split in ("TEST", "CALIBRATION"):
            section = bands[model][split]
            assert len(section["bands"]) == 6 and section["bands"][-1]["band"] == "[0.90, 1.00]"
            detail = evaluation[0]["model_details"][model]
            n = detail["test"]["rows"] if split == "TEST" else None
            if n is not None:
                assert sum(b["n"] for b in section["bands"]) == n
            for b in section["bands"]:
                assert (b["n"] == 0) == (b["observed_rate"] is None)
