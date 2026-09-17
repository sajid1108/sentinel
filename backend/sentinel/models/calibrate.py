"""Manual calibration on the CALIBRATION slice (§6.4, §7.2 P9). No CalibratedClassifierCV, no random folds.

return model: isotonic regression on base scores (plenty of positives)
abuse model:  sigmoid, a one-feature LogisticRegression on logit(clip(score, 1e-6, 1 - 1e-6))
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

ISOTONIC = "isotonic"
SIGMOID = "sigmoid"
CALIBRATION_METHODS = (ISOTONIC, SIGMOID)
LOGIT_EPS = 1e-6


def logit(scores) -> np.ndarray:
    s = np.clip(np.asarray(scores, dtype=float), LOGIT_EPS, 1 - LOGIT_EPS)
    return np.log(s / (1 - s)).reshape(-1, 1)


def fit_calibrator(method: str, scores, y):
    """Fit on base-model scores of CALIBRATION rows only."""
    y = np.asarray(y, dtype=int)
    if method == ISOTONIC:
        return IsotonicRegression(out_of_bounds="clip").fit(np.asarray(scores, dtype=float), y)
    if method == SIGMOID:
        return LogisticRegression().fit(logit(scores), y)
    raise ValueError(f"unknown calibration method {method!r}")


def apply_calibrator(method: str, calibrator, scores) -> np.ndarray:
    if method == ISOTONIC:
        out = calibrator.predict(np.asarray(scores, dtype=float))
    elif method == SIGMOID:
        out = calibrator.predict_proba(logit(scores))[:, 1]
    else:
        raise ValueError(f"unknown calibration method {method!r}")
    return np.clip(np.asarray(out, dtype=float), 0.0, 1.0)
