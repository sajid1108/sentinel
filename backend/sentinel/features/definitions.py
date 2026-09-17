"""Feature lists per model and feature_set_version (§6.2, §6.3).

The abuse list must never contain the §6.3 exclusions: matured return rate, prior returns, payment
method, CLV, or anything IP, pincode or name based. validate_abuse_features() enforces it at import.
"""
from __future__ import annotations

import hashlib
import json

FEATURE_SET_BASE = "fs-1.0"

# §6.2 return-hgb
RETURN_FEATURES: tuple[str, ...] = (
    "order_value_inr",
    "primary_category",
    "discount_pct",
    "n_items",
    "n_variants_same_product",
    "account_age_days",
    "prior_orders",
    "matured_return_rate_smoothed",
    "prior_returns_90d",
    "delivery_speed",
    "payment_method_cod",
)

# §6.3 abuse-hgb
ABUSE_FEATURES: tuple[str, ...] = (
    "order_value_inr",
    "primary_category",
    "account_age_days",
    "prior_orders",
    "prior_suspicious_claims_180d",
    "device_other_accounts_30d",
    "device_confirmed_abuse_weight",
    "token_other_accounts_30d",
    "address_other_accounts_weighted_30d",
    "component_size_reliable_90d",
    "component_abuse_ratio_smoothed",
    "confirmed_abuse_proximity",
    "linked_orders_24h",
    "linked_same_sku_7d",
    "identifier_reuse_velocity_7d",
    "component_recent_claims_30d",
    "new_device_for_account",
)

# Relationship features: the group set to reference values for the "without graph evidence" counterfactual (§6.5).
ABUSE_GRAPH_FEATURES: tuple[str, ...] = (
    "device_other_accounts_30d",
    "device_confirmed_abuse_weight",
    "token_other_accounts_30d",
    "address_other_accounts_weighted_30d",
    "component_size_reliable_90d",
    "component_abuse_ratio_smoothed",
    "confirmed_abuse_proximity",
    "linked_orders_24h",
    "linked_same_sku_7d",
    "identifier_reuse_velocity_7d",
    "component_recent_claims_30d",
)

CATEGORICAL_FEATURES = frozenset({"primary_category", "delivery_speed"})

# §6.3 "Deliberately excluded from the abuse model"
ABUSE_EXCLUDED_PREFIXES = ("matured_return_rate", "prior_returns", "payment_method", "clv")
ABUSE_EXCLUDED_TOKENS = frozenset({"ip", "pincode", "pin", "name", "names", "firstname", "lastname"})


def abuse_exclusion_violations(features) -> list[str]:
    bad = []
    for name in features:
        tokens = set(name.lower().split("_"))
        if name.lower().startswith(ABUSE_EXCLUDED_PREFIXES) or tokens & ABUSE_EXCLUDED_TOKENS \
                or "pincode" in name.lower():
            bad.append(name)
    return bad


def validate_abuse_features(features) -> None:
    bad = abuse_exclusion_violations(features)
    if bad:
        raise ValueError(f"abuse feature list contains excluded features (§6.3): {bad}")
    if not set(ABUSE_GRAPH_FEATURES) <= set(features):
        raise ValueError("graph feature group must be a subset of the abuse features")


def feature_set_version(return_features=RETURN_FEATURES, abuse_features=ABUSE_FEATURES) -> str:
    """"fs-1.0-" + the first 8 hex chars of SHA-256 over the sorted feature lists."""
    payload = json.dumps({"ABUSE": sorted(abuse_features), "RETURN": sorted(return_features)},
                         sort_keys=True, separators=(",", ":"))
    return f"{FEATURE_SET_BASE}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:8]}"


def all_features() -> tuple[str, ...]:
    """Return features, then the abuse features not already listed."""
    return RETURN_FEATURES + tuple(f for f in ABUSE_FEATURES if f not in RETURN_FEATURES)


validate_abuse_features(ABUSE_FEATURES)
FEATURE_SET_VERSION = feature_set_version()
