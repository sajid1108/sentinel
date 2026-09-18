"""§10.2 hash chain: canonical JSON, rounding before hashing, genesis, verification. No database needed."""
import json

import pytest

from sentinel.audit.chain import (GENESIS, canonical_json, compute_hash, round_for_hash, verify)


def test_genesis_is_64_zeros():
    assert GENESIS == "0" * 64


def test_canonical_json_is_stable_under_key_reordering():
    a = {"b": 1, "a": {"y": [1, 2], "x": "₹1,490"}}
    b = {"a": {"x": "₹1,490", "y": [1, 2]}, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert compute_hash(GENESIS, a) == compute_hash(GENESIS, b)


def test_canonical_json_is_compact_and_keeps_unicode():
    assert canonical_json({"display": "₹1,490", "n": 1}) == '{"display":"₹1,490","n":1}'


def test_hash_depends_on_the_previous_hash():
    payload = {"x": 1}
    assert compute_hash(GENESIS, payload) != compute_hash("f" * 64, payload)


def test_rounding_before_hashing():
    rounded = round_for_hash({"p_abuse": 0.12345678912, "cost": {"inr": 1490.004999, "display": "₹1,490"},
                              "weights": [0.1234567891], "flag": True, "count": 3})
    assert rounded == {"p_abuse": 0.123457, "cost": {"inr": 1490.0, "display": "₹1,490"},
                       "weights": [0.123457], "flag": True, "count": 3}


def test_rounded_payload_survives_a_json_round_trip():
    """What is stored is what was hashed: re-parsing the stored text reproduces the hash."""
    payload = round_for_hash({"p": 1 / 3, "m": {"inr": 2 / 3 * 1000, "display": "₹667"}})
    stored = canonical_json(payload)
    assert compute_hash(GENESIS, json.loads(stored)) == compute_hash(GENESIS, payload)


def _chain(n: int) -> list[dict]:
    rows, prev = [], GENESIS
    for seq in range(1, n + 1):
        payload = {"audit_event_id": f"E{seq}", "event_type": "DECISION_CREATED",
                   "occurred_at": "2026-09-01T05:00:00Z", "order_id": f"ORD-{seq}", "decision_id": f"D{seq}",
                   "actor": {"type": "SYSTEM", "id": "sentinel-scoring"}, "previous_action": None,
                   "new_action": "ALLOW", "policy_version": "v1.0",
                   "model_versions": {"return_model": "r", "abuse_model": "a"}, "p_abuse": 0.1 * seq}
        event_hash = compute_hash(prev, payload)
        rows.append({"seq": seq, "event_id": f"E{seq}", "event_type": "DECISION_CREATED",
                     "occurred_at": "2026-09-01T05:00:00.000000+00:00", "order_id": f"ORD-{seq}",
                     "decision_id": f"D{seq}", "actor_type": "SYSTEM", "actor_id": "sentinel-scoring",
                     "previous_action": None, "new_action": "ALLOW", "policy_version": "v1.0",
                     "return_model_version": "r", "abuse_model_version": "a",
                     "payload_json": canonical_json(payload), "prev_hash": prev, "event_hash": event_hash})
        prev = event_hash
    return rows


def test_verify_accepts_an_intact_chain():
    assert verify(_chain(5)) == (True, 5, None)


def test_verify_accepts_an_empty_chain():
    assert verify([]) == (True, 0, None)


@pytest.mark.parametrize("broken", [1, 3, 5])
def test_verify_reports_the_edited_payload_seq(broken):
    rows = _chain(5)
    payload = json.loads(rows[broken - 1]["payload_json"])
    payload["new_action"] = "BLOCK"
    rows[broken - 1]["payload_json"] = canonical_json(payload)
    valid, checked, seq = verify(rows)
    assert (valid, seq) == (False, broken) and checked == broken


def test_verify_detects_a_column_edited_beside_an_intact_payload():
    rows = _chain(3)
    rows[1]["new_action"] = "BLOCK"
    assert verify(rows) == (False, 2, 2)


def test_verify_detects_a_broken_link():
    rows = _chain(3)
    rows[2]["prev_hash"] = "1" * 64
    assert verify(rows)[2] == 3
