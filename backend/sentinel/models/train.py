"""Train return-hgb and abuse-hgb (§6.2-§6.4).

Models predict; they never choose actions. This package holds no thresholds and no policy logic.

Rows come from the orders' split column only: base models fit on TRAIN, calibrators on CALIBRATION.
Rows whose label is NULL are excluded (and counted). GAP, RECENT and TEST rows are never used here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier

from sentinel.features import definitions
from sentinel.models.calibrate import ISOTONIC, SIGMOID, apply_calibrator, fit_calibrator

TRAIN, CALIBRATION, TEST = "TRAIN", "CALIBRATION", "TEST"
MODEL_SPLITS = (TRAIN, CALIBRATION, TEST)

HGB_PARAMS = dict(max_depth=4, learning_rate=0.05, max_iter=300, l2_regularization=1.0,
                  categorical_features="from_dtype", early_stopping=False, random_state=7)

# Fixed category levels, stored in every bundle, so category codes never depend on the data seen.
CATEGORY_LEVELS: dict[str, tuple[str, ...]] = {
    "primary_category": ("APPAREL", "FOOTWEAR", "ELECTRONICS", "BEAUTY", "HOME", "ACCESSORIES"),
    "delivery_speed": ("STANDARD", "EXPRESS"),
}


# Monotonic constraints (deviation #25): more evidence never lowers the score. +1 = non-decreasing in the
# feature; every feature not listed is unconstrained (0), categoricals included. No -1 constraints.
ABUSE_MONOTONIC_INCREASING: tuple[str, ...] = (
    "prior_suspicious_claims_180d", "device_other_accounts_30d", "device_confirmed_abuse_weight",
    "token_other_accounts_30d", "address_other_accounts_weighted_30d", "component_abuse_ratio_smoothed",
    "confirmed_abuse_proximity", "linked_orders_24h", "linked_same_sku_7d", "identifier_reuse_velocity_7d",
    "component_recent_claims_30d",
)
RETURN_MONOTONIC_INCREASING: tuple[str, ...] = (
    "matured_return_rate_smoothed", "prior_returns_90d", "n_variants_same_product",
)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    features: tuple[str, ...]
    label: str
    calibration_method: str
    monotonic_increasing: tuple[str, ...]

    def monotonic_map(self, features=None) -> dict[str, int]:
        return {f: int(f in self.monotonic_increasing) for f in (features or self.features)}


MODEL_SPECS: dict[str, ModelSpec] = {
    "return": ModelSpec("return", definitions.RETURN_FEATURES, "return_label", ISOTONIC, RETURN_MONOTONIC_INCREASING),
    "abuse": ModelSpec("abuse", definitions.ABUSE_FEATURES, "abuse_label", SIGMOID, ABUSE_MONOTONIC_INCREASING),
}


@dataclass(frozen=True)
class TrainResult:
    bundle: dict
    train_order_ids: tuple[str, ...]
    calibration_order_ids: tuple[str, ...]


def design_matrix(df: pd.DataFrame, features, category_levels=CATEGORY_LEVELS) -> pd.DataFrame:
    """Model input: categoricals with the fixed levels (unknown values become missing), numbers as float."""
    X = pd.DataFrame(index=df.index)
    for name in features:
        if name in category_levels:
            X[name] = pd.Categorical(df[name].astype(object), categories=list(category_levels[name]))
        else:
            X[name] = df[name].astype("float64")
    return X


def labelled_rows(frame: pd.DataFrame, split: str, label: str) -> pd.DataFrame:
    """Rows of one split with a non-NULL label, in a stable order."""
    rows = frame[(frame["split"] == split) & frame[label].notna()].sort_values(["t0", "order_id"], kind="stable")
    assert (rows["split"] == split).all()
    return rows


def excluded_label_counts(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Rows dropped for a NULL label, per model split and label."""
    return {split: {spec.label: int(((frame["split"] == split) & frame[spec.label].isna()).sum())
                    for spec in MODEL_SPECS.values()}
            for split in MODEL_SPLITS}


def monotonic_cst(features, monotonic_map: dict[str, int]) -> list[int]:
    """Per-feature list aligned with the feature order; categoricals are always 0."""
    cst = [int(monotonic_map.get(f, 0)) for f in features]
    if any(c and f in CATEGORY_LEVELS for f, c in zip(features, cst)):
        raise ValueError("categorical features cannot carry a monotonic constraint")
    return cst


def fit_base(rows: pd.DataFrame, features, label: str, monotonic_map: dict[str, int]) -> HistGradientBoostingClassifier:
    model = HistGradientBoostingClassifier(**HGB_PARAMS, monotonic_cst=monotonic_cst(features, monotonic_map))
    model.fit(design_matrix(rows, features), rows[label].astype(int).to_numpy())
    return model


def _window(rows: pd.DataFrame, split: str, label: str) -> dict:
    return {"split": split, "rows": int(len(rows)), "positives": int((rows[label] == 1).sum()),
            "first_t0": rows["t0"].min().isoformat(), "last_t0": rows["t0"].max().isoformat()}


def _check_feature_set(frame: pd.DataFrame) -> None:
    versions = set(frame["feature_set_version"].unique())
    if versions != {definitions.FEATURE_SET_VERSION}:
        raise ValueError(f"feature table has feature_set_version {sorted(versions)}, expected "
                         f"{definitions.FEATURE_SET_VERSION}; rebuild features")


def train_model(spec: ModelSpec, frame: pd.DataFrame, trained_at: datetime,
                features: tuple[str, ...] | None = None) -> TrainResult:
    """Fit the base model on TRAIN and its calibrator on CALIBRATION."""
    _check_feature_set(frame)
    features = tuple(features or spec.features)
    train = labelled_rows(frame, TRAIN, spec.label)
    calibration = labelled_rows(frame, CALIBRATION, spec.label)
    monotonic = spec.monotonic_map(features)
    base = fit_base(train, features, spec.label, monotonic)
    scores = base.predict_proba(design_matrix(calibration, features))[:, 1]
    calibrator = fit_calibrator(spec.calibration_method, scores, calibration[spec.label].astype(int))
    bundle = {
        "name": spec.name,
        "base_model": base,
        "calibrator": calibrator,
        "calibration_method": spec.calibration_method,
        "feature_list": list(features),
        "category_levels": {k: list(v) for k, v in CATEGORY_LEVELS.items() if k in features},
        "label": spec.label,
        "hgb_params": dict(HGB_PARAMS),
        "monotonic_constraints": monotonic,
        "feature_set_version": definitions.FEATURE_SET_VERSION,
        "sklearn_version": sklearn.__version__,
        "train_window": _window(train, TRAIN, spec.label),
        "calibration_window": _window(calibration, CALIBRATION, spec.label),
        "trained_at": trained_at.isoformat(),
    }
    return TrainResult(bundle, tuple(train["order_id"]), tuple(calibration["order_id"]))


def train_all(frame: pd.DataFrame, trained_at: datetime) -> dict[str, TrainResult]:
    return {name: train_model(spec, frame, trained_at) for name, spec in MODEL_SPECS.items()}


def base_scores(bundle: dict, features_df: pd.DataFrame) -> np.ndarray:
    X = design_matrix(features_df, bundle["feature_list"], bundle["category_levels"])
    return bundle["base_model"].predict_proba(X)[:, 1]


def predict(bundle: dict, features_df: pd.DataFrame) -> np.ndarray:
    """Calibrated probabilities, one per row. Nothing else."""
    return apply_calibrator(bundle["calibration_method"], bundle["calibrator"], base_scores(bundle, features_df))
