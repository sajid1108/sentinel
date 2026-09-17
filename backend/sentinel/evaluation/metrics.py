"""Model metrics (§6.4, §13.3): PR-AUC with a seeded bootstrap CI, Brier score, ECE over equal-frequency bins,
reliability curve.

PR-AUC is average precision (step-wise, one point per distinct score), identical to
sklearn.metrics.average_precision_score; it is reimplemented in numpy only so the bootstrap is fast.
"""
from __future__ import annotations

import numpy as np

BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_SEED = 20260901
ECE_BINS = 10


def average_precision(y, p) -> float | None:
    """None when there is no positive (PR-AUC is undefined)."""
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    n_pos = int(y.sum())
    if n_pos == 0:
        return None
    order = np.argsort(-p, kind="mergesort")
    y_sorted, p_sorted = y[order], p[order]
    tp = np.cumsum(y_sorted)
    last_of_group = np.r_[np.flatnonzero(np.diff(p_sorted)), len(p_sorted) - 1]
    tp = tp[last_of_group]
    precision = tp / (last_of_group + 1)
    recall = tp / n_pos
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def bootstrap_ci(y, p, samples: int = BOOTSTRAP_SAMPLES, seed: int = BOOTSTRAP_SEED) -> tuple[float, float] | None:
    """Percentile 95 % CI of PR-AUC over row resamples; resamples without a positive are skipped."""
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    if y.sum() == 0:
        return None
    rng = np.random.default_rng(seed)
    n = len(y)
    values = []
    for _ in range(samples):
        idx = rng.integers(0, n, n)
        ap = average_precision(y[idx], p[idx])
        if ap is not None:
            values.append(ap)
    lo, hi = np.percentile(values, [2.5, 97.5])
    return float(lo), float(hi)


def brier(y, p) -> float:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.mean((p - y) ** 2))


def _quantile_bins(p, bins: int) -> list[np.ndarray]:
    order = np.argsort(np.asarray(p, dtype=float), kind="mergesort")
    return [b for b in np.array_split(order, min(bins, len(order))) if len(b)]


def reliability_curve(y, p, bins: int = ECE_BINS) -> list[dict]:
    """Equal-frequency bins over sorted predictions (ties split by row order)."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return [{"bin_mean_predicted": float(p[b].mean()), "observed_rate": float(y[b].mean()), "count": int(len(b))}
            for b in _quantile_bins(p, bins)]


def ece(y, p, bins: int = ECE_BINS) -> float:
    curve = reliability_curve(y, p, bins)
    n = sum(c["count"] for c in curve)
    return float(sum(c["count"] / n * abs(c["bin_mean_predicted"] - c["observed_rate"]) for c in curve))


def summary(y, p, with_ci: bool = True) -> dict:
    """n, positives, prevalence, pr_auc (+ CI), brier, ece. pr_auc keys are absent when undefined."""
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    out: dict = {"n": int(len(y)), "positives": int(y.sum())}
    if len(y) == 0:
        return out
    out["prevalence"] = float(y.mean())
    ap = average_precision(y, p)
    if ap is not None:
        out["pr_auc"] = ap
        if with_ci:
            lo, hi = bootstrap_ci(y, p)
            out["pr_auc_ci95_low"], out["pr_auc_ci95_high"] = lo, hi
    out["brier"] = brier(y, p)
    out["ece_10bin_quantile"] = ece(y, p)
    return out


# ── fixed risk bands (calibration where decisions are made) ──────────────────
RISK_BANDS: tuple[tuple[float, float], ...] = ((0.0, 0.05), (0.05, 0.20), (0.20, 0.50), (0.50, 0.70), (0.70, 0.90),
                                               (0.90, 1.00))
EQUAL_WIDTH_MIN_P = 0.05
WILSON_Z = 1.959963984540054


def wilson_interval(positives: int, n: int, z: float = WILSON_Z) -> tuple[float, float] | None:
    if n == 0:
        return None
    phat = positives / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return float(max(0.0, centre - half)), float(min(1.0, centre + half))


def risk_bands(y, p) -> list[dict]:
    """[lo, hi) bands; the last band includes 1.0. Empty bands carry n = 0 and nulls."""
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    out = []
    for k, (lo, hi) in enumerate(RISK_BANDS):
        last = k == len(RISK_BANDS) - 1
        mask = (p >= lo) & ((p <= hi) if last else (p < hi))
        n, pos = int(mask.sum()), int(y[mask].sum())
        ci = wilson_interval(pos, n)
        out.append({"band": f"[{lo:.2f}, {hi:.2f}" + ("]" if last else ")"), "n": n, "positives": pos,
                    "mean_predicted": float(p[mask].mean()) if n else None,
                    "observed_rate": pos / n if n else None,
                    "observed_ci95_wilson": list(ci) if ci else None})
    return out


def ece_equal_width_above(y, p, min_p: float = EQUAL_WIDTH_MIN_P, bins: int = ECE_BINS) -> dict:
    """ECE over `bins` equal-width bins spanning [min_p, 1.0] (last bin inclusive), rows with p >= min_p only,
    weighted by bin count within that subset."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    keep = p >= min_p
    y, p = y[keep], p[keep]
    n = len(p)
    if n == 0:
        return {"ece_10bin_equal_width_p_ge_0_05": None, "rows_p_ge_0_05": 0}
    edges = np.linspace(min_p, 1.0, bins + 1)
    which = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = which == b
        if m.any():
            total += m.sum() / n * abs(p[m].mean() - y[m].mean())
    return {"ece_10bin_equal_width_p_ge_0_05": float(total), "rows_p_ge_0_05": int(n)}
