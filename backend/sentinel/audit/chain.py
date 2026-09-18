"""Canonical JSON and the SHA-256 hash chain (§10.2).

event_hash = sha256(prev_hash + canonical_json(payload)), prev_hash of the first event = 64 zeros.

Values are rounded BEFORE hashing (money to 2 dp, every other float - probabilities, weights, attribution
points - to 6 dp), and what is stored is exactly what was hashed, so float formatting can never break
verification: a stored float re-serialises to the same text.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Iterable, NamedTuple

GENESIS = "0" * 64
MONEY_DP = 2
FLOAT_DP = 6


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(payload)).encode("utf-8")).hexdigest()


def _is_money(value: dict) -> bool:
    return set(value) == {"inr", "display"}


def round_for_hash(value):
    """Money {inr, display} to 2 dp, any other float to 6 dp; bools and ints untouched."""
    if isinstance(value, dict):
        if _is_money(value) and isinstance(value["inr"], (int, float)) and not isinstance(value["inr"], bool):
            return {"inr": round(float(value["inr"]), MONEY_DP), "display": value["display"]}
        return {k: round_for_hash(v) for k, v in value.items()}
    if isinstance(value, list):
        return [round_for_hash(v) for v in value]
    if isinstance(value, float):
        return round(value, FLOAT_DP)
    return value


class ChainVerification(NamedTuple):
    valid: bool
    events_checked: int
    first_broken_seq: int | None


# Row columns that must agree with the payload they sit beside; a column edited after the fact breaks
# the chain at that row even though the payload itself still hashes.
def _columns_match(row, payload: dict) -> bool:
    expected = {
        "event_id": payload.get("audit_event_id"),
        "event_type": payload.get("event_type"),
        "order_id": payload.get("order_id"),
        "decision_id": payload.get("decision_id"),
        "actor_type": (payload.get("actor") or {}).get("type"),
        "actor_id": (payload.get("actor") or {}).get("id"),
        "previous_action": payload.get("previous_action"),
        "new_action": payload.get("new_action"),
        "policy_version": payload.get("policy_version"),
        "return_model_version": (payload.get("model_versions") or {}).get("return_model"),
        "abuse_model_version": (payload.get("model_versions") or {}).get("abuse_model"),
    }
    if any(row[column] != value for column, value in expected.items()):
        return False
    try:
        return datetime.fromisoformat(row["occurred_at"]) == datetime.fromisoformat(payload["occurred_at"])
    except (KeyError, TypeError, ValueError):
        return False


def verify(rows: Iterable) -> ChainVerification:
    """rows: audit_events rows ordered by seq (mappings with the table's columns)."""
    prev = GENESIS
    checked = 0
    for row in rows:
        checked += 1
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            return ChainVerification(False, checked, row["seq"])
        if (row["prev_hash"] != prev or compute_hash(prev, payload) != row["event_hash"]
                or not _columns_match(row, payload)):
            return ChainVerification(False, checked, row["seq"])
        prev = row["event_hash"]
    return ChainVerification(True, checked, None)
