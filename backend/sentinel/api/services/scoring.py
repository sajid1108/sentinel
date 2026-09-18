"""ScoringService: one order in, one recorded decision out (§2, §9, §10; Phase 6).

    request -> FeatureBuilder (frozen as-of-DEMO_CLOCK history) -> calibrated p_return, p_abuse
            -> explain_order (attributions, reason codes) -> decide() -> decisions row + DECISION_CREATED
               audit event, written in ONE transaction.

Frozen history (architect amendment to P14, see DEVIATIONS): live-scored orders are written to the database
but never added to the in-memory graph, so every score is computed against the same as-of-DEMO_CLOCK
history and scoring is order-independent.

Degraded mode (G6, #14): if the models could not be loaded, the history could not be replayed, or feature
building or prediction raises, the decision is made without a score: p_return = p_abuse = None, no costs,
no cost-optimal action, the G6 fallback action and a recorded reason. The request never crashes.

The assessment core (`assess`, `graph_summary`, `write_decision`, `decision_payload`) is shared with the
seeding CLI so replayed backtest decisions are built by exactly the same code.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from sentinel.api.schemas import (Action, DiscountedLink, EvidenceSignal, GraphEvidenceSummary, GraphPayload,
                                  PolicyDecision, ReasonCode, ScoreOrderRequest, ScoreOrderResponse, Scores)
from sentinel.api.services.errors import Conflict, RequestRejected, UnknownAccount
from sentinel.api.services.graph_view import build_graph_payload
from sentinel.audit.chain import canonical_json
from sentinel.audit.schemas import AuditActor, AuditEventPayload, AuditModelVersions
from sentinel.audit.service import AppendedEvent, append_event, event_payload
from sentinel.db.models import immediate_transaction, parse_utc, read_connection, utc_iso
from sentinel.features.builder import FeatureBuilder, query_from_request
from sentinel.features.graph_state import from_micros, to_micros, visible
from sentinel.features.tabular_features import (OrderQuery, matured_return_counts, n_variants_same_product,
                                                order_value_inr, primary_category)
from sentinel.models import registry
from sentinel.models.explain import OrderExplanation, explain_order
from sentinel.models.reason_codes import component_confirmed_accounts
from sentinel.policy.config import PolicyConfig, load_policy_config
from sentinel.policy.engine import decide, decision_status
from sentinel.policy.guardrails import WEAK_SIGNAL_WEIGHT, DecisionContext, SignalInputs, corroborating_signals
from sentinel.settings import ARTIFACTS_DIR, DEMO_CLOCK

Source = Literal["DEMO", "LIVE", "BACKTEST_REPLAY"]

SYSTEM_ACTOR_ID = "sentinel-scoring"
# ld-1.0 (§7.1). Serving code may not import data/labels.py (P11); a test asserts the two agree.
LABEL_DEFINITION_VERSION = "ld-1.0"
# Deterministic ids for seeded decisions and events (uuid5); live decisions use uuid4.
ID_NAMESPACE = uuid.UUID("5e7a1d2c-9b64-4f0e-8a31-6c2d0b7f4e10")
# Masked label for an identifier first seen in a live request; same format as the generator's.
KIND_LABEL = {"DEVICE": "Device", "ADDRESS": "Address", "PAYMENT_TOKEN": "Payment token"}
DEGRADED_PREDICTION_TEXT = ("No model score is available: this decision was made in degraded mode, "
                            "without a prediction.")

_ORDER_KINDS = (("device_id", "DEVICE"), ("address_id", "ADDRESS"), ("payment_token_id", "PAYMENT_TOKEN"))


def seeded_decision_id(order_id: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, f"decision:{order_id}"))


def seeded_event_id(order_id: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, f"event:DECISION_CREATED:{order_id}"))


# ── models ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Models:
    bundles: dict[str, dict]
    reference: dict

    @property
    def versions(self) -> AuditModelVersions:
        r, a = self.bundles["return"], self.bundles["abuse"]
        return AuditModelVersions(return_model=r["model_version"], abuse_model=a["model_version"],
                                  feature_set=a["feature_set_version"], label_definition=LABEL_DEFINITION_VERSION,
                                  return_artifact_sha256=r["sha256"], abuse_artifact_sha256=a["sha256"])


def load_models(artifacts_dir: Path = ARTIFACTS_DIR) -> Models:
    """Both bundles and the reference vector, SHA-256 and version checked by the registry."""
    bundles = {name: registry.load_bundle(name, artifacts_dir) for name in registry.MODEL_NAMES}
    return Models(bundles, registry.load_reference(bundles, artifacts_dir))


def registry_versions(conn: sqlite3.Connection) -> AuditModelVersions:
    """Versions from the seeded model_registry table: what a degraded decision records when no bundle loaded."""
    rows = {r["model_name"]: r for r in conn.execute(
        "SELECT model_name, model_version, feature_set_version, artifact_sha256 FROM model_registry")}
    if not {"RETURN", "ABUSE"} <= set(rows):
        raise RuntimeError("model_registry is not seeded; run `python -m sentinel.cli seed-db`")
    return AuditModelVersions(return_model=rows["RETURN"]["model_version"],
                              abuse_model=rows["ABUSE"]["model_version"],
                              feature_set=rows["ABUSE"]["feature_set_version"],
                              label_definition=LABEL_DEFINITION_VERSION,
                              return_artifact_sha256=rows["RETURN"]["artifact_sha256"],
                              abuse_artifact_sha256=rows["ABUSE"]["artifact_sha256"])


# ── assessment core (shared with seeding) ────────────────────────────────────
@dataclass(frozen=True)
class Assessment:
    features: dict
    explanation: OrderExplanation | None      # None when degraded
    graph_summary: GraphEvidenceSummary
    decision: PolicyDecision
    degraded_reason: str | None = None

    @property
    def degraded(self) -> bool:
        return self.explanation is None


def graph_summary(features: dict, signals: list[EvidenceSignal],
                  discounted_links: list[DiscountedLink]) -> GraphEvidenceSummary:
    proximity = float(features["confirmed_abuse_proximity"])
    present = [s for s in signals if s.present]
    return GraphEvidenceSummary(
        component_size_reliable_90d=int(features["component_size_reliable_90d"]),
        confirmed_abusive_accounts_in_component=component_confirmed_accounts(features),
        # proximity = 1 / (1 + hops), so hops is recovered exactly; 0 means none within 6 hops
        min_hops_to_confirmed_abuse=round(1.0 / proximity - 1.0) if proximity > 0 else None,
        linked_orders_24h=int(features["linked_orders_24h"]),
        corroborating_signal_count=sum(1 for s in signals if s.present and s.counts_for_corroboration),
        signals=list(signals),
        discounted_links=list(discounted_links),
        # evidence was observed, but none of it carries the weight G4 requires for BLOCK
        weak_evidence_only=bool(present) and all(s.weight < WEAK_SIGNAL_WEIGHT for s in present),
    )


EMPTY_GRAPH_SUMMARY = GraphEvidenceSummary(
    component_size_reliable_90d=0, confirmed_abusive_accounts_in_component=0, min_hops_to_confirmed_abuse=None,
    linked_orders_24h=0, corroborating_signal_count=0, signals=[], discounted_links=[], weak_evidence_only=False)


def assess(*, features: dict, signal_inputs: SignalInputs, discounted_links: list[DiscountedLink],
           device_evidence: dict, matured: tuple[int, int] | None, models: Models, cfg: PolicyConfig,
           order_value: float, clv_inr: float, decided_at: datetime, graph_state_as_of: datetime,
           predict_hook: Callable[[], None] | None = None) -> Assessment | str:
    """Explain and decide one order. Returns the degraded reason (a str) if prediction fails.

    `decide()` runs outside the prediction guard on purpose: a policy error is a bug and must surface,
    not be absorbed into degraded mode.
    """
    returns, matured_orders = matured if matured is not None else (None, None)
    try:
        if predict_hook is not None:
            predict_hook()
        explanation = explain_order(
            models.bundles, models.reference, features, discounted_links,
            device_confirmed_accounts=device_evidence.get("device_confirmed_peer_count"),
            device_last_confirmed_days=device_evidence.get("device_most_recent_confirmation_days"),
            matured_returns=returns, matured_orders=matured_orders)
    except Exception as exc:                                       # G6: never crash the request
        return f"prediction failed ({type(exc).__name__})"
    signals = corroborating_signals(signal_inputs)
    ctx = DecisionContext(p_abuse=explanation.p_abuse, p_return=explanation.p_return, order_value_inr=order_value,
                          clv_inr=clv_inr, signals=signals, decided_at=decided_at,
                          graph_state_as_of=graph_state_as_of)
    return Assessment(features, explanation, graph_summary(features, signals, discounted_links), decide(ctx, cfg))


def degraded_assessment(order_value: float, cfg: PolicyConfig, decided_at: datetime, reason: str) -> Assessment:
    """G6: no score exists, so none is recorded and no cost is shown (#14)."""
    ctx = DecisionContext(p_abuse=None, p_return=None, order_value_inr=order_value,
                          clv_inr=cfg.clv.new_customer_floor_inr, signals=(), decided_at=decided_at,
                          graph_state_as_of=None, degraded=True, degraded_reason=reason)
    return Assessment({}, None, EMPTY_GRAPH_SUMMARY, decide(ctx, cfg), reason)


def reason_codes(assessment: Assessment) -> list[ReasonCode]:
    """Increasing codes in evidence order, then mitigating codes (direction tells them apart)."""
    e = assessment.explanation
    if e is None:
        return []
    return [ReasonCode.model_validate(vars(code)) for code in [*e.reasons, *e.mitigating_reasons]]


def _plain(value):
    return value.item() if hasattr(value, "item") else value


def decision_payload(*, event_id: str, occurred_at: datetime, decision_id: str, order_id: str,
                     features_as_of: datetime, assessment: Assessment, versions: AuditModelVersions,
                     actor_id: str = SYSTEM_ACTOR_ID) -> AuditEventPayload:
    e, d = assessment.explanation, assessment.decision
    return AuditEventPayload(
        audit_event_id=event_id, event_type="DECISION_CREATED", occurred_at=occurred_at, order_id=order_id,
        decision_id=decision_id, actor=AuditActor(type="SYSTEM", id=actor_id), features_as_of=features_as_of,
        p_return=None if e is None else e.p_return,
        p_abuse=None if e is None else e.p_abuse,
        p_abuse_without_graph_evidence=None if e is None else e.p_abuse_without_graph_evidence,
        reason_codes=[r.code for r in reason_codes(assessment)],
        feature_attributions_pp={} if e is None else dict(e.feature_attributions_pp),
        prediction_explanation=DEGRADED_PREDICTION_TEXT if e is None else e.prediction_explanation,
        graph_summary=assessment.graph_summary,
        candidate_actions=d.costs, cost_optimal_action=d.cost_optimal_action, selected_action=d.selected_action,
        policy_rule=d.selected_rule, guardrails=d.guardrails, policy_explanation=d.policy_explanation,
        policy_version=d.policy_version, policy_config_sha256=d.policy_config_sha256, model_versions=versions,
        degraded_mode=e is None, original_recommendation=d.selected_action, previous_action=None,
        new_action=d.selected_action, override=None, appeal=None)


_INSERT_DECISION = """
INSERT INTO decisions (decision_id, order_id, scored_at, features_as_of, feature_set_version, features_json,
                       p_return, p_abuse, p_abuse_without_graph, return_model_version, abuse_model_version,
                       policy_version, cost_optimal_action, recommended_action, current_action, status,
                       selected_rule, costs_json, guardrails_json, reasons_json, graph_summary_json,
                       degraded_mode, source, latest_audit_event_id, discounted_links_json, graph_payload_json)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _json(models: list) -> str:
    return canonical_json([m.model_dump(mode="json") for m in models])


def write_decision(conn: sqlite3.Connection, *, decision_id: str, event_id: str, order_id: str,
                   scored_at: datetime, features_as_of: datetime, assessment: Assessment,
                   versions: AuditModelVersions, source: Source,
                   graph_payload: GraphPayload | None) -> AppendedEvent:
    """The decisions row and its DECISION_CREATED event. Caller holds BEGIN IMMEDIATE and commits both.

    `graph_payload` is the point-in-time reviewer graph captured with the decision (#32); None for a degraded
    decision. The discounted links are the graph summary's, stored in their own column."""
    e, d = assessment.explanation, assessment.decision
    action = d.selected_action.value
    conn.execute(_INSERT_DECISION, (
        decision_id, order_id, utc_iso(scored_at), utc_iso(features_as_of), versions.feature_set,
        canonical_json({k: _plain(v) for k, v in assessment.features.items()}),
        None if e is None else e.p_return, None if e is None else e.p_abuse,
        None if e is None else e.p_abuse_without_graph_evidence,
        versions.return_model, versions.abuse_model, d.policy_version,
        None if d.cost_optimal_action is None else d.cost_optimal_action.value, action, action,
        decision_status(d.selected_action), d.selected_rule, _json(d.costs), _json(d.guardrails),
        _json(reason_codes(assessment)), canonical_json(assessment.graph_summary.model_dump(mode="json")),
        int(e is None), source, event_id, _json(assessment.graph_summary.discounted_links),
        None if graph_payload is None else canonical_json(graph_payload.model_dump(mode="json"))))
    return append_event(conn, decision_payload(
        event_id=event_id, occurred_at=scored_at, decision_id=decision_id, order_id=order_id,
        features_as_of=features_as_of, assessment=assessment, versions=versions))


# ── reading a decision back ──────────────────────────────────────────────────
def decision_row(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM decisions WHERE order_id = ?", (order_id,)).fetchone()


def created_event_payload(conn: sqlite3.Connection, decision_id: str) -> dict:
    row = conn.execute("SELECT event_id FROM audit_events WHERE decision_id = ? AND event_type = 'DECISION_CREATED'",
                       (decision_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"decision {decision_id} has no DECISION_CREATED event")
    return event_payload(conn, row["event_id"])


def response_from_db(conn: sqlite3.Connection, order_id: str, cfg: PolicyConfig,
                     idempotent_replay: bool) -> ScoreOrderResponse:
    """The decision as recorded: scores from the decisions row (full precision), explanation text from its
    DECISION_CREATED event, status and audit_event_id as they stand now."""
    row = decision_row(conn, order_id)
    created = created_event_payload(conn, row["decision_id"])
    policy = PolicyDecision(
        policy_version=row["policy_version"], policy_config_sha256=created["policy_config_sha256"],
        cost_optimal_action=row["cost_optimal_action"], selected_action=row["recommended_action"],
        selected_rule=row["selected_rule"], costs=json.loads(row["costs_json"]),
        guardrails=json.loads(row["guardrails_json"]), policy_explanation=created["policy_explanation"],
        assumptions_notice=cfg.policy.notice)
    return ScoreOrderResponse(
        decision_id=row["decision_id"], order_id=order_id, scored_at=parse_utc(row["scored_at"]),
        features_as_of=parse_utc(row["features_as_of"]),
        scores=Scores(p_return=row["p_return"], p_abuse=row["p_abuse"],
                      p_abuse_without_graph_evidence=row["p_abuse_without_graph"],
                      return_model_version=row["return_model_version"],
                      abuse_model_version=row["abuse_model_version"],
                      feature_set_version=row["feature_set_version"]),
        prediction_explanation=created["prediction_explanation"],
        reasons=json.loads(row["reasons_json"]), graph_summary=json.loads(row["graph_summary_json"]),
        policy=policy, status=row["status"], audit_event_id=row["latest_audit_event_id"],
        degraded_mode=bool(row["degraded_mode"]), idempotent_replay=idempotent_replay)


# ── idempotency ──────────────────────────────────────────────────────────────
def request_fingerprint(request: ScoreOrderRequest) -> str:
    """SHA-256 of the request's canonical JSON, with placed_at normalised to UTC."""
    body = request.model_dump(mode="json")
    body["placed_at"] = utc_iso(request.placed_at)
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def stored_request(conn: sqlite3.Connection, order_id: str) -> ScoreOrderRequest:
    """Rebuild the request an order row was created from (lines in line order)."""
    o = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    lines = conn.execute("SELECT * FROM order_lines WHERE order_id = ? ORDER BY line_no", (order_id,)).fetchall()
    return ScoreOrderRequest(
        order_id=o["order_id"], account_id=o["account_id"], placed_at=parse_utc(o["placed_at"]),
        lines=[{"sku_id": ln["sku_id"], "product_id": ln["product_id"], "variant": ln["variant"],
                "category": ln["category"], "unit_price_inr": ln["unit_price_inr"], "quantity": ln["quantity"]}
               for ln in lines],
        discount_pct=o["discount_pct"], delivery_speed=o["delivery_speed"], payment_method=o["payment_method"],
        device_id=o["device_id"], address_id=o["address_id"], payment_token_id=o["payment_token_id"])


# ── history (frozen) ─────────────────────────────────────────────────────────
_TIMESTAMPS = {"accounts": ("created_at",), "identifiers": ("multi_tenant_set_at",), "orders": ("placed_at",),
               "order_events": ("occurred_at",)}
_HISTORY_SQL = {
    "accounts": "SELECT account_id, created_at, source FROM accounts",
    "identifiers": "SELECT identifier_id, kind, is_multi_tenant, multi_tenant_set_at, display_label FROM identifiers",
    "orders": "SELECT * FROM orders WHERE source = 'HISTORY'",
    "order_lines": "SELECT l.* FROM order_lines l JOIN orders o USING (order_id) WHERE o.source = 'HISTORY'",
    "order_events": "SELECT e.* FROM order_events e JOIN orders o USING (order_id) WHERE o.source = 'HISTORY'",
}


def load_history(engine) -> dict[str, pd.DataFrame]:
    """The as-of-DEMO_CLOCK world from the database. Live-scored orders (source DEMO/LIVE) are excluded:
    the scoring history is frozen, so a restart scores exactly as the first start did."""
    with read_connection(engine) as conn:
        world = {name: pd.read_sql_query(sql, conn) for name, sql in _HISTORY_SQL.items()}
    for name, columns in _TIMESTAMPS.items():
        for column in columns:
            world[name][column] = pd.to_datetime(world[name][column], utc=True, format="ISO8601")
    return world


# ── the service ──────────────────────────────────────────────────────────────
class ScoringService:
    """Constructed once at startup; `score` is safe to call repeatedly and in any order."""

    def __init__(self, engine, policy_config: PolicyConfig, models: Models | None, builder: FeatureBuilder | None,
                 startup_error: str | None = None):
        self.engine = engine
        self.cfg = policy_config
        self.models = models
        self.builder = builder
        self.startup_error = startup_error
        # Test seam for G6: called with a stage name ("features", "predict") and may raise. Never set in
        # production; there is no configuration flag that enables degraded mode.
        self.fault_hook: Callable[[str], None] | None = None

    @classmethod
    def start(cls, engine, artifacts_dir: Path = ARTIFACTS_DIR,
              policy_config: PolicyConfig | None = None) -> "ScoringService":
        cfg = policy_config or load_policy_config()
        errors = []
        try:
            models = load_models(artifacts_dir)
        except Exception as exc:                                   # G6: serve degraded, never refuse to start
            models = None
            errors.append(f"model loading failed ({type(exc).__name__}: {exc})")
        try:
            builder = FeatureBuilder.replay(load_history(engine), DEMO_CLOCK, cfg)
        except Exception as exc:
            builder = None
            errors.append(f"graph state unavailable ({type(exc).__name__}: {exc})")
        return cls(engine, cfg, models, builder, "; ".join(errors) or None)

    @property
    def graph_state_as_of(self) -> datetime | None:
        return None if self.builder is None else self.builder.graph_state_as_of

    def _stage(self, name: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(name)

    # -- public --
    def score(self, request: ScoreOrderRequest, source: Literal["DEMO", "LIVE"]) -> ScoreOrderResponse:
        if source not in ("DEMO", "LIVE"):
            raise ValueError(f"live scoring source must be DEMO or LIVE, not {source!r}")
        if request.placed_at > DEMO_CLOCK:
            raise RequestRejected("placed_at is after the demo clock; the system cannot score the future")
        with read_connection(self.engine) as conn:
            replay = self._replay_or_none(conn, request)
            if replay is not None:
                return replay
            if conn.execute("SELECT 1 FROM accounts WHERE account_id = ?", (request.account_id,)).fetchone() is None:
                raise UnknownAccount(f"unknown account {request.account_id}")

        query = query_from_request(request)
        assessment, graph_payload = self._assess(request, query)
        decision_id, event_id = str(uuid.uuid4()), str(uuid.uuid4())
        with immediate_transaction(self.engine) as conn:
            if decision_row(conn, request.order_id) is None:          # re-checked under the write lock
                self._insert_order(conn, request, query, source)
                write_decision(conn, decision_id=decision_id, event_id=event_id, order_id=request.order_id,
                               scored_at=DEMO_CLOCK, features_as_of=request.placed_at, assessment=assessment,
                               versions=self._versions(conn), source=source, graph_payload=graph_payload)
                fresh = True
            else:
                fresh = False
        with read_connection(self.engine) as conn:
            if not fresh:
                return self._replay_or_none(conn, request)
            return response_from_db(conn, request.order_id, self.cfg, idempotent_replay=False)

    # -- steps --
    def _replay_or_none(self, conn: sqlite3.Connection, request: ScoreOrderRequest) -> ScoreOrderResponse | None:
        if conn.execute("SELECT 1 FROM orders WHERE order_id = ?", (request.order_id,)).fetchone() is None:
            return None
        if decision_row(conn, request.order_id) is None:
            raise Conflict(f"order {request.order_id} already exists and was never scored")
        if request_fingerprint(stored_request(conn, request.order_id)) != request_fingerprint(request):
            raise Conflict(f"order {request.order_id} was already scored with a different payload")
        return response_from_db(conn, request.order_id, self.cfg, idempotent_replay=True)

    def _versions(self, conn: sqlite3.Connection) -> AuditModelVersions:
        return self.models.versions if self.models is not None else registry_versions(conn)

    def _assess(self, request: ScoreOrderRequest, query: OrderQuery) -> tuple[Assessment, GraphPayload | None]:
        """The assessment and the point-in-time reviewer graph (#32; None when degraded)."""
        value = order_value_inr(query)
        if self.models is None or self.builder is None:
            return degraded_assessment(value, self.cfg, DEMO_CLOCK,
                                       self.startup_error or "model or graph state unavailable"), None
        b, t0 = self.builder, request.placed_at
        last = b.state.last_applied
        if last is not None and not visible(last, to_micros(t0)):
            raise RequestRejected("placed_at precedes the end of the frozen scoring history; features as of that "
                                  "time would see later events")
        try:
            self._stage("features")
            features = b.features_for_request(request, t0)
            signal_inputs = b.signal_inputs(request, t0)
            links = b.discounted_links(request, t0)
            evidence = b.evidence_values(request, t0)
            matured = matured_return_counts(b.state, request.account_id, to_micros(t0))
            clv = b.clv_inr(request.account_id, t0)
            graph_payload = build_graph_payload(b.ego_view(query, to_micros(t0)), query, to_micros(t0),
                                                from_micros(to_micros(t0)))       # as_of in UTC, like every record
        except Exception as exc:                                   # G6: never crash the request
            return degraded_assessment(value, self.cfg, DEMO_CLOCK,
                                       f"feature building failed ({type(exc).__name__})"), None
        result = assess(features=features, signal_inputs=signal_inputs, discounted_links=links,
                        device_evidence=evidence, matured=matured, models=self.models, cfg=self.cfg,
                        order_value=value, clv_inr=clv, decided_at=DEMO_CLOCK,
                        graph_state_as_of=b.graph_state_as_of, predict_hook=lambda: self._stage("predict"))
        if isinstance(result, str):
            return degraded_assessment(value, self.cfg, DEMO_CLOCK, result), None
        return result, graph_payload

    @staticmethod
    def _insert_order(conn: sqlite3.Connection, request: ScoreOrderRequest, query: OrderQuery, source: str) -> None:
        """The order as the server derives it: value from the lines, never from the client."""
        for field, kind in _ORDER_KINDS:
            ident = getattr(request, field)
            if ident is not None:
                conn.execute("INSERT OR IGNORE INTO identifiers (identifier_id, kind, is_multi_tenant, "
                             "multi_tenant_set_at, display_label) VALUES (?, ?, 0, NULL, ?)",
                             (ident, kind, f"{KIND_LABEL[kind]} ••{ident[-4:]}"))
        conn.execute(
            "INSERT INTO orders (order_id, account_id, placed_at, order_value_inr, discount_pct, n_items, "
            "n_variants_same_product, primary_category, delivery_speed, payment_method, device_id, address_id, "
            "payment_token_id, source, split) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (request.order_id, request.account_id, utc_iso(request.placed_at), order_value_inr(query),
             request.discount_pct, sum(ln.quantity for ln in request.lines), n_variants_same_product(query),
             primary_category(query), request.delivery_speed, request.payment_method, request.device_id,
             request.address_id, request.payment_token_id, source))
        conn.executemany(
            "INSERT INTO order_lines (order_id, line_no, sku_id, product_id, variant, category, unit_price_inr, "
            "quantity) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(request.order_id, i, ln.sku_id, ln.product_id, ln.variant, ln.category, ln.unit_price_inr, ln.quantity)
             for i, ln in enumerate(request.lines, start=1)])
