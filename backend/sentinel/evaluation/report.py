"""Phase 4 evaluation → backend/artifacts/reports/evaluation.json (§6.4, §9.5, §13.3).

Model metrics are computed on TEST (labelled rows) with the committed, verified bundles. The no-graph abuse
model exists only here, for the graph-uplift comparison, and is never saved. The backtest scores strategies
by realized cost at the true label. Nothing here feeds back into the models or the policy.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sentinel.api.schemas import CalibrationPoint, ModelEvaluation
from sentinel.evaluation import backtest as B
from sentinel.evaluation import metrics as M
from sentinel.evaluation.cohorts import HARD_NEGATIVE_ARCHETYPES, cohort_columns, groups, value_band
from sentinel.evaluation.splits import OfflineData
from sentinel.features.definitions import ABUSE_FEATURES, ABUSE_GRAPH_FEATURES, FEATURE_SET_VERSION
from sentinel.money import make_money
from sentinel.models.train import CALIBRATION, MODEL_SPECS, TEST, predict, train_model
from sentinel.policy.config import PolicyConfig
from sentinel.settings import DEMO_CLOCK

DATA_NOTICE = ("Synthetic data is used to validate the architecture, policy behaviour, auditability, "
               "and coordinated-pattern detection. Real deployment would require merchant-specific "
               "historical data and prospective validation.")
COLD_START_RING = "R3"
COLD_START_MIN_P_ABUSE = 0.5
SEPARATION_ARCHETYPE = "FREQUENT_RETURNER"
LABEL_VARIANTS = {"UNRESOLVED_AS_0": 0, "UNRESOLVED_AS_1": 1}
MODEL_LABEL = {"return": "RETURN", "abuse": "ABUSE"}
NO_GRAPH_FEATURES = tuple(f for f in ABUSE_FEATURES if f not in ABUSE_GRAPH_FEATURES)


@dataclass
class Provenance:
    """Order ids each part of the evaluation used (for split-hygiene checks)."""
    model_metric_rows: dict[str, tuple[str, ...]] = field(default_factory=dict)
    no_graph_train_rows: tuple[str, ...] = ()
    no_graph_calibration_rows: tuple[str, ...] = ()
    backtest_rows: tuple[str, ...] = ()
    tuning_rows: tuple[str, ...] = ()


def ids_digest(order_ids) -> str:
    return hashlib.sha256("\n".join(sorted(order_ids)).encode("utf-8")).hexdigest()


def _rows_record(order_ids) -> dict:
    return {"rows": len(order_ids), "order_ids_sha256": ids_digest(order_ids)}


def evaluation_frame(data: OfflineData) -> pd.DataFrame:
    shared = [c for c in data.policy_inputs.columns if c in data.frame.columns and c != "order_id"]
    check = data.frame[["order_id", *shared]].merge(data.policy_inputs[["order_id", *shared]], on="order_id")
    for column in shared:                      # e.g. SignalInputs fields that are also §6.3 features
        if not (check[f"{column}_x"] == check[f"{column}_y"]).all():
            raise ValueError(f"features.parquet and policy_inputs.parquet disagree on {column}; rebuild features")
    policy = data.policy_inputs.drop(columns=shared)
    frame = (data.frame.merge(policy, on="order_id", how="left", validate="one_to_one")
             .merge(data.truth[["order_id", "archetype", "ring_id"]], on="order_id", how="left",
                    validate="one_to_one"))
    return frame.sort_values(["t0", "order_id"], kind="stable").reset_index(drop=True)


def labels_for(frame: pd.DataFrame, label: str, variant: str | None = None) -> pd.Series:
    """The label column; with a variant, UNRESOLVED abuse rows take that variant's value."""
    y = frame[label].astype("Float64")
    if variant is not None and label == "abuse_label":
        y = y.mask(frame["abuse_status"] == "UNRESOLVED", float(LABEL_VARIANTS[variant]))
    return y


# ── model metrics ────────────────────────────────────────────────────────────
def _cohort_metrics(y, p, labels) -> dict[str, dict[str, float]]:
    return {name: M.summary(y[mask], p[mask]) for name, mask in groups(labels)}


def model_evaluation(name: str, bundle: dict, rows: pd.DataFrame, y: np.ndarray, p: np.ndarray) -> ModelEvaluation:
    s = M.summary(y, p)
    by_cohort = {}
    for cohort, labels in cohort_columns(rows).items():
        for value, metrics in _cohort_metrics(y, p, labels).items():
            by_cohort[f"{cohort}={value}"] = metrics
    return ModelEvaluation(
        model=MODEL_LABEL[name], model_version=bundle["model_version"], pr_auc=s["pr_auc"],
        pr_auc_ci95=(s["pr_auc_ci95_low"], s["pr_auc_ci95_high"]), brier=s["brier"],
        ece_10bin_quantile=s["ece_10bin_quantile"],
        calibration_curve=[CalibrationPoint(**c) for c in M.reliability_curve(y, p)],
        by_value_band=_cohort_metrics(y, p, value_band(rows["order_value_inr"])),
        by_cohort=by_cohort)


def _labelled(frame: pd.DataFrame, split: str, label: str, variant: str | None = None):
    y = labels_for(frame, label, variant)
    mask = (frame["split"] == split) & y.notna()
    return frame[mask], y[mask].astype(int).to_numpy()


# ── backtest ─────────────────────────────────────────────────────────────────
def _backtest(frame: pd.DataFrame, cfg: PolicyConfig, variant: str | None, prov: Provenance | None = None) -> dict:
    test, y_test = _labelled(frame, TEST, "abuse_label", variant)
    calib, y_calib = _labelled(frame, CALIBRATION, "abuse_label", variant)
    cm_test, cm_calib = B.cost_matrix(test, y_test, cfg), B.cost_matrix(calib, y_calib, cfg)
    tuning = B.tune_fixed_threshold(calib, calib["p_abuse"].to_numpy(), cm_calib)
    decisions = B.sentinel_decisions(test, test["p_abuse"], test["p_return"], cfg)
    actions = {
        "SENTINEL": decisions.selected,
        "FIXED_THRESHOLD": B.fixed_threshold_actions(test["p_abuse"], tuning.tau_review, tuning.tau_block),
        "RULE_BASED": B.rule_based_actions(test),
        "ALLOW_ALL": B.allow_all_actions(len(test)),
    }
    if prov is not None:
        prov.backtest_rows, prov.tuning_rows = tuple(test["order_id"]), tuning.order_ids
    strategies, extras = [], {}
    for name in B.STRATEGIES:
        result, extra = B.strategy_backtest(name, actions[name], cm_test, cfg)
        strategies.append(result.model_dump(mode="json"))
        extras[name] = extra
    return {"test": test, "cm": cm_test, "actions": actions, "decisions": decisions,
            "strategies": strategies, "extras": extras,
            "tuning": tuning, "calibration_rows": _rows_record(tuning.order_ids),
            "test_rows": _rows_record(test["order_id"])}


def _action_distributions(test: pd.DataFrame, actions: dict) -> dict:
    ring = test["ring_id"].fillna("")
    out = {}
    for name, a in actions.items():
        out[name] = {"overall": B.action_distribution(a),
                     "rings": {r: B.action_distribution(a[(ring == r).to_numpy()])
                               for r in sorted(set(ring) - {""})}}
    return out


def _archetype_backtest(bt: dict, cfg: PolicyConfig) -> dict:
    test, cm = bt["test"], bt["cm"]
    out = {}
    for archetype in ("NORMAL", *HARD_NEGATIVE_ARCHETYPES):
        mask = (test["archetype"] == archetype).to_numpy()
        sub = B.CostMatrix(cm.total[mask], cm.operational[mask], cm.genuine[mask], cm.abusive[mask], cm.margin[mask])
        out[archetype] = {name: {k: v for k, v in B.strategy_backtest(name, bt["actions"][name][mask], sub, cfg)[0]
                                 .model_dump(mode="json").items() if k in ("genuine_block_rate",
                                                                            "customer_friction_rate",
                                                                            "manual_reviews_per_1000")}
                          for name in B.STRATEGIES}
        out[archetype]["orders"] = int(mask.sum())
        out[archetype]["genuine"] = int((~cm.abusive[mask]).sum())
    return out


# ── abuse extras ─────────────────────────────────────────────────────────────
def _r3_recall(frame: pd.DataFrame, column: str, variant: str | None = None) -> dict:
    test, y = _labelled(frame, TEST, "abuse_label", variant)
    mask = ((test["ring_id"] == COLD_START_RING).to_numpy()) & (y == 1)
    n = int(mask.sum())
    hits = int((test[column].to_numpy()[mask] >= COLD_START_MIN_P_ABUSE).sum())
    return {"abusive_orders": n, "at_or_above_0_5": hits, "recall": hits / n if n else 0.0}


def _abuse_headline(frame: pd.DataFrame, variant: str | None) -> dict:
    test, y = _labelled(frame, TEST, "abuse_label", variant)
    full = M.summary(y, test["p_abuse"].to_numpy())
    no_graph = M.summary(y, test["p_abuse_no_graph"].to_numpy(), with_ci=False)
    return {"abuse_model": full, "no_graph_pr_auc": no_graph.get("pr_auc"),
            "graph_uplift_pr_auc": full["pr_auc"] - no_graph["pr_auc"],
            "cold_start_ring_recall": {"full": _r3_recall(frame, "p_abuse", variant),
                                       "no_graph": _r3_recall(frame, "p_abuse_no_graph", variant)}}


# ── entry point ──────────────────────────────────────────────────────────────
def run_evaluation(data: OfflineData, bundles: dict[str, dict], cfg: PolicyConfig) -> tuple[dict, Provenance]:
    prov = Provenance()
    frame = evaluation_frame(data)
    frame["p_return"] = predict(bundles["return"], frame)
    frame["p_abuse"] = predict(bundles["abuse"], frame)
    no_graph = train_model(MODEL_SPECS["abuse"], data.frame, DEMO_CLOCK, features=NO_GRAPH_FEATURES)
    prov.no_graph_train_rows, prov.no_graph_calibration_rows = no_graph.train_order_ids, no_graph.calibration_order_ids
    frame["p_abuse_no_graph"] = predict(no_graph.bundle, frame)

    models, model_details = [], {}
    for name, spec in MODEL_SPECS.items():
        column = f"p_{name}"
        test, y = _labelled(frame, TEST, spec.label)
        calib, y_calib = _labelled(frame, CALIBRATION, spec.label)
        prov.model_metric_rows[name] = tuple(test["order_id"])
        evaluation = model_evaluation(name, bundles[name], test, y, test[column].to_numpy())
        models.append(evaluation.model_dump(mode="json"))
        model_details[MODEL_LABEL[name]] = {
            "model_version": bundles[name]["model_version"],
            "calibration_method": bundles[name]["calibration_method"],
            "test": {"rows": len(test), "positives": int(y.sum()), "prevalence": float(y.mean())},
            "calibration_slice_ece_10bin_quantile": M.ece(y_calib, calib[column].to_numpy()),
            "test_rows": _rows_record(test["order_id"]),
        }
    abuse_ece = model_details["ABUSE"]
    abuse_ece["ece_warning"] = next(m["ece_10bin_quantile"] for m in models if m["model"] == "ABUSE") > 0.05

    headline = _abuse_headline(frame, None)
    fr_test = frame[(frame["split"] == TEST) & (frame["archetype"] == SEPARATION_ARCHETYPE)]
    separation = float(np.corrcoef(fr_test["p_return"], fr_test["p_abuse"])[0, 1]) if len(fr_test) > 1 else 0.0

    bt = _backtest(frame, cfg, None, prov)
    report = {
        "data_notice": DATA_NOTICE,
        "as_of": DEMO_CLOCK.isoformat(),
        "versions": {"feature_set_version": FEATURE_SET_VERSION, "policy_version": cfg.policy.version,
                     "policy_config_sha256": cfg.config_sha256,
                     "return_model_version": bundles["return"]["model_version"],
                     "abuse_model_version": bundles["abuse"]["model_version"]},
        "excluded_label_rows": excluded_rows(frame),
        "models": models,
        "model_details": model_details,
        "graph_uplift": {"test_pr_auc_full": headline["abuse_model"]["pr_auc"],
                         "test_pr_auc_no_graph": headline["no_graph_pr_auc"],
                         "uplift": headline["graph_uplift_pr_auc"],
                         "no_graph_features": list(NO_GRAPH_FEATURES),
                         "note": "Evaluation-only model: same parameters and sigmoid calibration, never saved."},
        "cold_start_ring_recall": headline["cold_start_ring_recall"]["full"]["recall"],
        "cold_start_ring_recall_detail": {"ring": COLD_START_RING, "min_p_abuse": COLD_START_MIN_P_ABUSE,
                                          **headline["cold_start_ring_recall"]},
        "separation": {"archetype": SEPARATION_ARCHETYPE, "test_orders": len(fr_test),
                       "pearson_p_return_p_abuse": separation},
        "backtest": bt["strategies"],
        "backtest_details": {
            "rows": {"test": bt["test_rows"], "fixed_threshold_tuning_calibration": bt["calibration_rows"]},
            "cost_basis": "Realized cost at the true abuse label; abusive loss scaled by returned_value_fraction "
                          "when the order was returned. Expected cost is never used to score a strategy.",
            "fixed_threshold": {"tau_review": bt["tuning"].tau_review, "tau_block": bt["tuning"].tau_block,
                                "calibration_realized_cost_per_1000": make_money(
                                    bt["tuning"].realized_cost_per_1000).model_dump()},
            "per_strategy": bt["extras"],
            "action_distribution": _action_distributions(bt["test"], bt["actions"]),
            "by_archetype": _archetype_backtest(bt, cfg),
        },
        "guardrail_cost": B.guardrail_cost(bt["test"], bt["cm"], bt["decisions"],
                                           B.unconstrained_actions(bt["test"], bt["test"]["p_abuse"], cfg),
                                           bt["actions"]["FIXED_THRESHOLD"]),
        "calibration_bands": calibration_bands(frame),
        "sensitivity": cost_sensitivity(frame, cfg),
        "label_sensitivity": label_sensitivity(frame, cfg),
        "drift_monitoring": "PLACEHOLDER_NOT_COMPUTED",
    }
    return report, prov


def calibration_bands(frame: pd.DataFrame) -> dict:
    """Fixed risk bands and equal-width ECE on p >= 0.05, for both models on TEST and CALIBRATION labelled rows.
    Diagnostic only: nothing is recalibrated."""
    out = {}
    for name, spec in MODEL_SPECS.items():
        column = f"p_{name}"
        out[MODEL_LABEL[name]] = {}
        for split in (TEST, CALIBRATION):
            rows, y = _labelled(frame, split, spec.label)
            p = rows[column].to_numpy()
            out[MODEL_LABEL[name]][split] = {"bands": M.risk_bands(y, p), **M.ece_equal_width_above(y, p)}
    return out


def excluded_rows(frame: pd.DataFrame) -> dict:
    out = {}
    for split in ("TRAIN", "CALIBRATION", "TEST"):
        rows = frame[frame["split"] == split]
        out[split] = {
            "rows": len(rows),
            "return_label_null": int(rows["return_label"].isna().sum()),
            "abuse_label_null": int(rows["abuse_label"].isna().sum()),
            "abuse_label_null_by_status": {k: int(v) for k, v in
                                           rows.loc[rows["abuse_label"].isna(), "abuse_status"]
                                           .value_counts().sort_index().items()},
        }
    return out


def cost_sensitivity(frame: pd.DataFrame, cfg: PolicyConfig) -> list[dict]:
    """Realized cost per 1,000 for every strategy with one config group at ×0.5 and ×1.5 (rates clipped)."""
    rows = []
    for group in B.COST_GROUPS:
        for factor in B.COST_FACTORS:
            bt = _backtest(frame, B.scaled_config(cfg, group, factor), None)
            row = {"group": group, "factor": factor, "fixed_threshold_tau_review": bt["tuning"].tau_review,
                   "fixed_threshold_tau_block": bt["tuning"].tau_block}
            for s in bt["strategies"]:
                row[f"{s['strategy']}_realized_cost_per_1000_inr"] = s["realized_cost_per_1000"]["inr"]
            rows.append(row)
    return rows


def label_sensitivity(frame: pd.DataFrame, cfg: PolicyConfig) -> dict:
    """UNRESOLVED abuse rows treated as 0, then as 1, in TEST metrics and in the backtest (FIXED_THRESHOLD
    re-tuned on CALIBRATION under the same treatment). Models are not retrained; return metrics do not use
    the abuse label and are unchanged."""
    out = {}
    for variant in LABEL_VARIANTS:
        headline = _abuse_headline(frame, variant)
        bt = _backtest(frame, cfg, variant)
        out[variant] = {
            "abuse_model_test": headline["abuse_model"],
            "no_graph_test_pr_auc": headline["no_graph_pr_auc"],
            "graph_uplift_pr_auc": headline["graph_uplift_pr_auc"],
            "cold_start_ring_recall": headline["cold_start_ring_recall"],
            "fixed_threshold": {"tau_review": bt["tuning"].tau_review, "tau_block": bt["tuning"].tau_block},
            "backtest": bt["strategies"],
            "test_rows": bt["test_rows"],
        }
    return out
