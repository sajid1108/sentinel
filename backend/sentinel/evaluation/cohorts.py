"""Evaluation cohorts (§6.4, §13.3). Offline only: archetype and ring come from ground truth."""
from __future__ import annotations

import numpy as np
import pandas as pd

HARD_NEGATIVE_ARCHETYPES = ("HOUSEHOLD", "OFFICE_HOSTEL_PG", "REFURB_DEVICE")
VALUE_BANDS = ("<₹2k", "₹2–10k", ">₹10k")
AGE_BANDS = ("<30 d", "30–365 d", ">365 d")


def value_band(order_value_inr) -> np.ndarray:
    v = np.asarray(order_value_inr, dtype=float)
    return np.where(v < 2_000, VALUE_BANDS[0], np.where(v <= 10_000, VALUE_BANDS[1], VALUE_BANDS[2]))


def age_band(account_age_days) -> np.ndarray:
    a = np.asarray(account_age_days, dtype=float)
    return np.where(a < 30, AGE_BANDS[0], np.where(a <= 365, AGE_BANDS[1], AGE_BANDS[2]))


def cohort_columns(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Cohort name -> label per row. Needs order_value_inr, account_age_days, address_is_multi_tenant,
    payment_method, primary_category and archetype."""
    return {
        "account_age": age_band(df["account_age_days"]),
        "multi_tenant_address": np.where(df["address_is_multi_tenant"].astype(bool), "yes", "no"),
        "payment": np.where(df["payment_method"] == "COD", "COD", "PREPAID"),
        "primary_category": df["primary_category"].astype(str).to_numpy(),
        "archetype": df["archetype"].astype(str).to_numpy(),
    }


def groups(labels: np.ndarray) -> list[tuple[str, np.ndarray]]:
    return [(str(value), labels == value) for value in sorted(set(labels.tolist()))]
