"""Append-only audit service (§10): write one event into the hash chain, read events, verify the chain.

`append_event` must run inside an open `BEGIN IMMEDIATE` transaction (db.models.immediate_transaction): it
reads the last event_hash and inserts under the same write lock, so two writers can never chain onto the
same predecessor. The caller commits, together with whatever state change the event records.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from sentinel.audit.chain import GENESIS, ChainVerification, canonical_json, compute_hash, round_for_hash, verify
from sentinel.audit.schemas import AuditEventPayload
from sentinel.db.models import read_connection, utc_iso

_INSERT = """
INSERT INTO audit_events (event_id, event_type, occurred_at, order_id, decision_id, actor_type, actor_id,
                          previous_action, new_action, policy_version, return_model_version,
                          abuse_model_version, payload_json, prev_hash, event_hash)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass(frozen=True)
class AppendedEvent:
    seq: int
    event_id: str
    prev_hash: str
    event_hash: str


def hashable_payload(payload: AuditEventPayload) -> dict:
    """The exact dict that is hashed and stored: JSON mode, then rounded (§10.2)."""
    return round_for_hash(payload.model_dump(mode="json"))


def last_event_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT event_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    return GENESIS if row is None else row[0]


def append_event(conn: sqlite3.Connection, payload: AuditEventPayload) -> AppendedEvent:
    if not conn.in_transaction:
        raise RuntimeError("append_event must run inside BEGIN IMMEDIATE (db.models.immediate_transaction)")
    body = hashable_payload(payload)
    prev = last_event_hash(conn)
    event_hash = compute_hash(prev, body)
    cursor = conn.execute(_INSERT, (
        payload.audit_event_id, payload.event_type, utc_iso(payload.occurred_at), payload.order_id,
        payload.decision_id, payload.actor.type, payload.actor.id,
        None if payload.previous_action is None else payload.previous_action.value, payload.new_action.value,
        payload.policy_version, payload.model_versions.return_model, payload.model_versions.abuse_model,
        canonical_json(body), prev, event_hash))
    return AppendedEvent(cursor.lastrowid, payload.audit_event_id, prev, event_hash)


def event_payload(conn: sqlite3.Connection, event_id: str) -> dict:
    row = conn.execute("SELECT payload_json FROM audit_events WHERE event_id = ?", (event_id,)).fetchone()
    if row is None:
        raise KeyError(f"no audit event {event_id!r}")
    return json.loads(row[0])


def events_for_order(conn: sqlite3.Connection, order_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM audit_events WHERE order_id = ? ORDER BY seq", (order_id,)).fetchall()


def verify_chain(engine) -> ChainVerification:
    """(valid, events_checked, first_broken_seq) over the whole table, in seq order."""
    with read_connection(engine) as conn:
        return verify(conn.execute("SELECT * FROM audit_events ORDER BY seq"))
