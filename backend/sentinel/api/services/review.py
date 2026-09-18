"""Reviewer actions (§9.3 H1/H2, §9.4, §10): override and appeal, each one audit event.

An override changes only `current_action`, `status` and `latest_audit_event_id`; the DB trigger protects
everything else, including `recommended_action` (H2). Every event repeats the decision's scores, costs,
versions and graph summary (§10.1), copied from its DECISION_CREATED event, so it can be read on its own.

State is read and written under one BEGIN IMMEDIATE lock, so a stale `expected_current_action` is detected
against the state the write will actually change.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sentinel.api.schemas import Action, AppealRequest, OverrideRequest, OverrideResponse
from sentinel.api.services.errors import Conflict, NotFound, RequestRejected
from sentinel.api.services.scoring import created_event_payload, decision_row
from sentinel.audit.schemas import AuditActor, AuditAppeal, AuditEventPayload, AuditOverride
from sentinel.audit.service import append_event
from sentinel.db.models import immediate_transaction
from sentinel.settings import DEMO_CLOCK

G2_OVERRIDE_REASON = "INDEPENDENT_EVIDENCE_OF_ABUSE"
G2_WARNING = "Override to BLOCK without corroboration (G2 unmet) — recorded"
APPEAL_PREFIX = "APL"


class DemoReviewerClock:
    """When a reviewer acted, in the demo world (DEVIATIONS #33): DEMO_CLOCK + wall time elapsed since the
    clock was created (service start). Monotonic, never jumps from 2026-09-01 to the real date, and keeps
    the real order and spacing of reviewer actions. Tests inject a fixed clock instead."""

    def __init__(self, anchor: datetime = DEMO_CLOCK):
        self.anchor = anchor
        self._started = time.monotonic()

    def __call__(self) -> datetime:
        return self.anchor + timedelta(seconds=time.monotonic() - self._started)


@dataclass(frozen=True)
class AppealResult:
    order_id: str
    decision_id: str
    appeal_reference: str
    opened_at: datetime
    audit_event_id: str


def _g2_satisfied(created: dict) -> bool:
    """G2 held for the recorded decision. A degraded decision evaluated no G2, so it has no corroboration."""
    g2 = [g for g in created["guardrails"] if g["guardrail_id"] == "G2"]
    return bool(g2) and not g2[0]["triggered"]


def _event(created: dict, **changes) -> AuditEventPayload:
    """A new event built on the decision's own record: same scores, costs, versions and graph summary."""
    return AuditEventPayload.model_validate({**created, **changes})


class ReviewService:
    def __init__(self, engine, clock: Callable[[], datetime] | None = None):
        self.engine = engine
        self.clock = clock if clock is not None else DemoReviewerClock()

    @staticmethod
    def _decision(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
        row = decision_row(conn, order_id)
        if row is None:
            raise NotFound(f"no decision for order {order_id}")
        return row

    def apply_override(self, order_id: str, request: OverrideRequest, reviewer_id: str) -> OverrideResponse:
        now = self.clock()
        event_id = str(uuid.uuid4())
        with immediate_transaction(self.engine) as conn:
            row = self._decision(conn, order_id)
            current = Action(row["current_action"])
            if request.expected_current_action is not current:
                raise Conflict(f"expected current action {request.expected_current_action.value}, "
                               f"but it is {current.value}")
            created = created_event_payload(conn, row["decision_id"])
            conflicts, warnings = [], []
            if request.new_action is Action.BLOCK and not _g2_satisfied(created):
                if request.reason_category != G2_OVERRIDE_REASON:
                    raise RequestRejected("overriding to BLOCK without G2 corroboration requires reason_category "
                                          f"{G2_OVERRIDE_REASON}")
                conflicts, warnings = ["G2"], [G2_WARNING]
            payload = _event(
                created, audit_event_id=event_id, event_type="OVERRIDE_APPLIED", occurred_at=now,
                actor=AuditActor(type="REVIEWER", id=reviewer_id), previous_action=current,
                new_action=request.new_action, original_recommendation=row["recommended_action"],
                override=AuditOverride(reason_category=request.reason_category, reason_text=request.reason_text,
                                       reviewer_id=reviewer_id, reviewed_at=now, guardrail_conflicts=conflicts),
                appeal=None)
            conn.execute("UPDATE decisions SET current_action = ?, status = 'OVERRIDDEN', latest_audit_event_id = ? "
                         "WHERE decision_id = ?", (request.new_action.value, event_id, row["decision_id"]))
            append_event(conn, payload)
        return OverrideResponse(order_id=order_id, decision_id=row["decision_id"],
                                original_recommendation=row["recommended_action"], previous_action=current,
                                new_action=request.new_action, reviewer_id=reviewer_id, overridden_at=now,
                                audit_event_id=event_id, warnings=warnings)

    def open_appeal(self, order_id: str, request: AppealRequest, actor_id: str) -> AppealResult:
        now = self.clock()
        event_id = str(uuid.uuid4())
        with immediate_transaction(self.engine) as conn:
            row = self._decision(conn, order_id)
            if row["status"] == "APPEAL_OPEN":
                raise Conflict(f"an appeal is already open for order {order_id}")
            # sequential across the whole system, counted under the write lock
            opened = conn.execute("SELECT COUNT(*) FROM audit_events WHERE event_type = 'APPEAL_OPENED'").fetchone()[0]
            reference = f"{APPEAL_PREFIX}-{now.year}-{opened + 1:06d}"
            current = Action(row["current_action"])
            payload = _event(
                created_event_payload(conn, row["decision_id"]), audit_event_id=event_id,
                event_type="APPEAL_OPENED", occurred_at=now, actor=AuditActor(type="REVIEWER", id=actor_id),
                previous_action=current, new_action=current, original_recommendation=row["recommended_action"],
                override=None,
                appeal=AuditAppeal(appeal_reference=reference, channel=request.channel, note=request.note,
                                   status="OPEN"))
            conn.execute("UPDATE decisions SET status = 'APPEAL_OPEN', latest_audit_event_id = ? WHERE decision_id = ?",
                         (event_id, row["decision_id"]))
            append_event(conn, payload)
        return AppealResult(order_id, row["decision_id"], reference, now, event_id)
