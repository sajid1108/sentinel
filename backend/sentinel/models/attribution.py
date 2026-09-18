"""Ablation attributions on the calibrated models (§6.5).

For feature j: delta_j = p(x) - p(x with x_j := reference_j), in probability points, where the reference
is the typical genuine CALIBRATION order built by `cli build-reference`.

Deltas are NOT additive and must never be summed. Each answers "what if this one feature had been
typical"; the model's interactions mean the answers overlap, so adding them is meaningless. This module
deliberately exposes no function that adds them together, and the group counterfactual is its own
ablation rather than a sum of the group's individual deltas.

Cost: exactly one predict_proba per model per order. The baseline row, one row per ablated feature and
one row per ablated group are built as a single batch and scored together.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sentinel.models.calibrate import apply_calibrator

PP = 100.0  # probabilities are reported in probability points


@dataclass(frozen=True)
class Ablation:
    """One order through one model: the score as it stands, per-feature deltas, and group counterfactuals."""
    p: float
    deltas: dict[str, float]                 # probability points, positive = the observed value raised the score
    group_p: dict[str, float]                # group name -> probability with the whole group set to reference
    group_delta_pp: dict[str, float]         # group name -> (p - group_p) in probability points


def _reference_values(reference: dict) -> dict:
    return reference["values"] if "values" in reference else reference


def _calibrated(bundle: dict, design: pd.DataFrame) -> np.ndarray:
    """Calibrated probabilities for a design matrix _batch already built to the bundle's schema.

    This is train.predict() without its design_matrix pass: _batch produces exactly the dtypes
    design_matrix would, and re-deriving them per request costs more than the model call itself.
    """
    scores = bundle["base_model"].predict_proba(design)[:, 1]
    return apply_calibrator(bundle["calibration_method"], bundle["calibrator"], scores)


def _batch(bundle: dict, row: dict, values: dict, groups: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    """Baseline row, then one row per single-feature ablation, then one row per group ablation."""
    features = tuple(bundle["feature_list"])
    levels = bundle["category_levels"]
    missing = [f for f in features if f not in values]
    if missing:
        raise KeyError(f"reference vector has no value for {missing}; rebuild with `cli build-reference`")

    # variant i says which features row i replaces with their reference value; None is the baseline
    variants: list[frozenset[str]] = [frozenset()]
    variants += [frozenset((f,)) for f in features]
    variants += [frozenset(g) & set(features) for g in groups.values()]

    data: dict[str, object] = {}
    for f in features:
        observed, ref = row[f], values[f]
        if f in levels:
            column = [ref if f in v else observed for v in variants]
            data[f] = pd.Categorical(column, categories=list(levels[f]))
        else:
            column = np.full(len(variants), float(observed), dtype="float64")
            for i, v in enumerate(variants):
                if f in v:
                    column[i] = float(ref)
            data[f] = column
    return pd.DataFrame(data, columns=list(features))


def ablation(bundle: dict, reference: dict, row: dict, groups: dict[str, tuple[str, ...]] | None = None) -> Ablation:
    """Everything this model can say about one order, in a single batched predict."""
    groups = dict(groups or {})
    features = tuple(bundle["feature_list"])
    probabilities = _calibrated(bundle, _batch(bundle, row, _reference_values(reference), groups))
    base = float(probabilities[0])
    deltas = {f: (base - float(p)) * PP for f, p in zip(features, probabilities[1: 1 + len(features)])}
    group_p = {name: float(p) for name, p in zip(groups, probabilities[1 + len(features):])}
    return Ablation(base, deltas, group_p, {n: (base - p) * PP for n, p in group_p.items()})


def attributions(bundle: dict, reference: dict, row: dict) -> dict[str, float]:
    """Per-feature ablation deltas in probability points (§6.5)."""
    return ablation(bundle, reference, row).deltas


def group_attribution(bundle: dict, reference: dict, row: dict, group) -> dict[str, float]:
    """The group counterfactual: the probability with the whole group set to reference, and the delta.

    For ABUSE_GRAPH_FEATURES this produces p_abuse_without_graph_evidence. It is one ablation of the
    same model, never a separate model, and never the sum of the group's individual deltas.
    """
    result = ablation(bundle, reference, row, {"group": tuple(group)})
    return {"p": result.p, "p_without_group": result.group_p["group"],
            "delta_pp": result.group_delta_pp["group"]}
