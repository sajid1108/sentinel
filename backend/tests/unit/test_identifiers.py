"""features/identifiers.py: normalisation, HMAC and placeholder rejection (§5, §6.1)."""
import hashlib
import hmac

import pytest

from sentinel.features.identifiers import (PLACEHOLDER_IDS, PlaceholderIdentifierError, identifier_id,
                                           is_rejected_id, normalise)
from sentinel.settings import HMAC_SECRET


def test_identifier_id_is_hmac_prefix_of_kind_and_value():
    expected = hmac.new(HMAC_SECRET.encode(), b"DEVICE:phone-1", hashlib.sha256).hexdigest()[:32]
    assert identifier_id("DEVICE", "phone-1") == expected


def test_normalisation_trims_and_collapses_whitespace():
    assert normalise("  12  Main\tRoad ") == "12 Main Road"
    assert identifier_id("ADDRESS", " 12 Main  Road") == identifier_id("ADDRESS", "12 Main Road")


@pytest.mark.parametrize("value", ["", "   ", "unknown", "UNKNOWN", "null", "0000000000", "00:00:00:00", None])
def test_placeholder_values_are_never_hashed(value):
    with pytest.raises(PlaceholderIdentifierError):
        identifier_id("DEVICE", value)


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        identifier_id("IP", "10.0.0.1")


@pytest.mark.parametrize("ident", ["", "unknown", "0" * 32, "not-hex", "A" * 32, None])
def test_rejected_ids(ident):
    assert is_rejected_id(ident)


def test_hashed_placeholders_are_on_the_denylist():
    unknown = hmac.new(HMAC_SECRET.encode(), b"DEVICE:unknown", hashlib.sha256).hexdigest()[:32]
    assert unknown in PLACEHOLDER_IDS and is_rejected_id(unknown)
    assert not is_rejected_id(identifier_id("DEVICE", "phone-1"))
