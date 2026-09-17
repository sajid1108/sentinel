"""Identifier normalisation, HMAC hashing and placeholder rejection (§5, §6.1, Appendix D).

identifier_id(kind, value) = HMAC-SHA256(secret, f"{kind}:{normalised value}")[:32].

Placeholders (empty, "unknown", all-zero and the denylist below) are never hashed: identifier_id
raises PlaceholderIdentifierError. Hashed ids of those placeholders, and the all-zero id, are on
PLACEHOLDER_IDS so a hashed identifier that arrives from outside can be rejected as well; the
graph never turns one into a node.

This module is shared by the generator and by serving code, so it imports nothing from
sentinel.data.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata

from sentinel.settings import HMAC_SECRET

KINDS = ("DEVICE", "ADDRESS", "PAYMENT_TOKEN")
ID_LENGTH = 32
_HEX_ID = re.compile(r"^[a-f0-9]{32}$")

# Raw values that mean "no identifier" (compared after normalisation, case-insensitively).
PLACEHOLDER_VALUES = frozenset({
    "", "unknown", "null", "none", "nil", "na", "n/a", "undefined", "default", "test",
    "not available", "not_available", "-", "?",
})


class PlaceholderIdentifierError(ValueError):
    """Raised when a raw identifier value is a placeholder and must not be hashed."""


def normalise(value: str | None) -> str:
    """NFKC, trimmed, internal whitespace collapsed to one space. Case is preserved."""
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split())


def is_placeholder_value(value: str | None) -> bool:
    v = normalise(value)
    if v.casefold() in PLACEHOLDER_VALUES:
        return True
    stripped = re.sub(r"[\s:\-_.]", "", v)
    return stripped == "" or set(stripped) == {"0"} or set(stripped.casefold()) == {"f"}


def _hmac32(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()[:ID_LENGTH]


def identifier_id(kind: str, value: str, secret: str = HMAC_SECRET) -> str:
    """§5: HMAC-SHA256(secret, f"{kind}:{value}")[:32] over the normalised value."""
    if kind not in KINDS:
        raise ValueError(f"unknown identifier kind {kind!r}")
    if is_placeholder_value(value):
        raise PlaceholderIdentifierError(f"placeholder {kind} identifier")
    return _hmac32(secret, f"{kind}:{normalise(value)}")


def placeholder_ids(secret: str = HMAC_SECRET) -> frozenset[str]:
    """Hashed forms of every placeholder value for every kind, plus the all-zero id."""
    ids = {"0" * ID_LENGTH}
    for kind in KINDS:
        for value in PLACEHOLDER_VALUES:
            for variant in {value, value.upper(), value.capitalize()}:
                ids.add(_hmac32(secret, f"{kind}:{variant}"))
    return frozenset(ids)


PLACEHOLDER_IDS = placeholder_ids()


def is_rejected_id(ident: str | None) -> bool:
    """True for identifiers that must never become graph nodes (§6.1 "Rejected identifiers")."""
    if ident is None:
        return True
    ident = str(ident)
    if ident.strip().casefold() in PLACEHOLDER_VALUES:
        return True
    if not _HEX_ID.fullmatch(ident):
        return True
    return ident in PLACEHOLDER_IDS or set(ident) == {"0"}
