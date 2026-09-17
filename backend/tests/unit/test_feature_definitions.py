"""§6.2/§6.3 feature lists, §6.3 exclusions and feature_set_version."""
import re

import pytest

from sentinel.features import definitions as F


def test_lists_match_the_contract():
    assert len(F.RETURN_FEATURES) == 11 and len(F.ABUSE_FEATURES) == 17
    assert len(set(F.ABUSE_FEATURES)) == len(F.ABUSE_FEATURES)
    assert set(F.ABUSE_GRAPH_FEATURES) < set(F.ABUSE_FEATURES)


@pytest.mark.parametrize("family", ["matured_return_rate", "prior_returns", "payment_method", "clv", "ip", "pincode",
                                    "name"])
def test_abuse_list_excludes_forbidden_families(family):
    assert not [f for f in F.ABUSE_FEATURES if f.startswith(family) or family in f.split("_")]


@pytest.mark.parametrize("bad", ["matured_return_rate_smoothed", "prior_returns_90d", "payment_method_cod", "clv_inr",
                                 "ip_address_accounts", "shipping_pincode", "customer_name_match"])
def test_exclusion_check_rejects(bad):
    with pytest.raises(ValueError):
        F.validate_abuse_features(F.ABUSE_FEATURES + (bad,))


def test_return_features_keep_their_return_history():
    assert {"matured_return_rate_smoothed", "prior_returns_90d", "payment_method_cod"} <= set(F.RETURN_FEATURES)


def test_feature_set_version_format_and_sensitivity():
    assert re.fullmatch(r"fs-1\.0-[0-9a-f]{8}", F.FEATURE_SET_VERSION)
    assert F.feature_set_version() == F.FEATURE_SET_VERSION
    assert F.feature_set_version(F.RETURN_FEATURES, F.ABUSE_FEATURES[:-1]) != F.FEATURE_SET_VERSION
    assert F.feature_set_version(F.RETURN_FEATURES + ("extra",), F.ABUSE_FEATURES) != F.FEATURE_SET_VERSION
    assert F.feature_set_version(tuple(reversed(F.RETURN_FEATURES)), F.ABUSE_FEATURES) == F.FEATURE_SET_VERSION
