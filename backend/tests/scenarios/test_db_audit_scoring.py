"""Phase 6: seeding, the audit chain, ScoringService, degraded mode and reviewer actions, on real databases.

Self-contained: the world is generated in-process (session fixture), written to a temporary data directory
with its features, and seeded into temporary database files. Nothing under backend/data is read or written.
Every probability comes from the committed models; nothing here sets one.
"""
import itertools
import json
import shutil
import sqlite3
import time
from datetime import timedelta

import pytest

from sentinel.api.schemas import Action, AppealRequest, OverrideRequest, ScoreOrderRequest
from sentinel.api.services.errors import Conflict, NotFound, RequestRejected
from sentinel.api.services.graph_view import identifier_node_id
from sentinel.api.services.review import G2_WARNING, ReviewService
from sentinel.api.services.scoring import ScoringService, load_history, load_models
from sentinel.audit.service import verify_chain
from sentinel.data.demo_orders import demo_requests
from sentinel.data.generator import write_outputs
from sentinel.db.models import get_engine, read_connection, utc_iso
from sentinel.db.seed import SEEDED_DECISIONS, DemoModeOff, reset_demo, seed_database
from sentinel.evaluation.backtest import ACTIONS, sentinel_actions
from sentinel.evaluation.demos import score_demos
from sentinel.features.builder import WORLD_TABLES, FeatureBuilder, build_tables
from sentinel.features.graph_state import NODE_PREFIX, node_id
from sentinel.models import predict
from sentinel.policy.config import load_policy_config
from sentinel.settings import DEMO_CLOCK

pytestmark = pytest.mark.slow

SEED_BUDGET_S = 30.0
DEMO_ACTIONS = {"ORD-DEMO-001": Action.ALLOW, "ORD-DEMO-002": Action.BLOCK, "ORD-DEMO-003": Action.MANUAL_REVIEW}


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def data_dir(world, tmp_path_factory):
    path = tmp_path_factory.mktemp("data")
    write_outputs(world, path)
    features, policy = build_tables(world)
    features.to_parquet(path / "features.parquet", index=False)
    policy.to_parquet(path / "policy_inputs.parquet", index=False)
    return path


@pytest.fixture(scope="module")
def seeded(data_dir, tmp_path_factory):
    path = tmp_path_factory.mktemp("seeded") / "sentinel.db"
    start = time.perf_counter()
    report = seed_database(path, data_dir=data_dir)
    return path, report, time.perf_counter() - start


@pytest.fixture(scope="module")
def cfg():
    return load_policy_config()


@pytest.fixture(scope="module")
def models():
    return load_models()


@pytest.fixture(scope="module")
def builder(seeded, cfg):
    """The frozen as-of-DEMO_CLOCK history, replayed once from the seeded database."""
    engine = get_engine(seeded[0])
    try:
        return FeatureBuilder.replay(load_history(engine), DEMO_CLOCK, cfg)
    finally:
        engine.dispose()


def _fresh(seeded, tmp_path, name="fresh.db"):
    path = tmp_path / name
    shutil.copy(seeded[0], path)
    return get_engine(path)


@pytest.fixture
def engine(seeded, tmp_path):
    engine = _fresh(seeded, tmp_path)
    yield engine
    engine.dispose()


@pytest.fixture
def service(engine, cfg, models, builder):
    return ScoringService(engine, cfg, models, builder)


def _requests() -> dict[str, ScoreOrderRequest]:
    return {p["order_id"]: ScoreOrderRequest.model_validate(p) for p in demo_requests()}


def _rows(engine, sql, *args):
    with read_connection(engine) as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _count(engine, table):
    return _rows(engine, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]


# ── seeding ──────────────────────────────────────────────────────────────────
def test_seeding_writes_exactly_250_backtest_replay_decisions(seeded):
    path, report, _ = seeded
    engine = get_engine(path)
    try:
        assert _count(engine, "decisions") == SEEDED_DECISIONS
        assert _rows(engine, "SELECT DISTINCT source FROM decisions") == [{"source": "BACKTEST_REPLAY"}]
        assert _count(engine, "audit_events") == SEEDED_DECISIONS
        assert report.by_source == {"BACKTEST_REPLAY": SEEDED_DECISIONS}
    finally:
        engine.dispose()


def test_seeding_includes_every_non_allow_test_order(seeded):
    _, report, _ = seeded
    assert report.non_allow_test_orders <= SEEDED_DECISIONS
    assert report.non_allow_test_orders + report.allow_filled == SEEDED_DECISIONS
    non_allow = sum(n for a, n in report.by_action.items() if a != "ALLOW")
    assert non_allow == report.non_allow_test_orders


def test_seeded_actions_equal_the_backtest_sentinel_actions(seeded, data_dir, models, cfg):
    """Built independently the way evaluation/report.py builds its backtest rows."""
    import pandas as pd
    features = pd.read_parquet(data_dir / "features.parquet")
    policy = pd.read_parquet(data_dir / "policy_inputs.parquet")
    shared = [c for c in policy.columns if c in features.columns and c != "order_id"]
    rows = features[features["split"] == "TEST"].merge(policy.drop(columns=shared), on="order_id")
    actions = sentinel_actions(rows, predict(models.bundles["abuse"], rows), predict(models.bundles["return"], rows), cfg)
    backtest = {oid: ACTIONS[i].value for oid, i in zip(rows["order_id"], actions)}
    engine = get_engine(seeded[0])
    try:
        seeded_actions = {r["order_id"]: r["recommended_action"]
                          for r in _rows(engine, "SELECT order_id, recommended_action FROM decisions")}
    finally:
        engine.dispose()
    assert seeded_actions == {oid: backtest[oid] for oid in seeded_actions}
    assert {oid for oid, a in backtest.items() if a != "ALLOW"} <= set(seeded_actions)


def test_seeded_events_are_chronological_at_t0(seeded):
    engine = get_engine(seeded[0])
    try:
        rows = _rows(engine, "SELECT a.seq, a.occurred_at, d.features_as_of, d.scored_at FROM audit_events a "
                             "JOIN decisions d USING (decision_id) ORDER BY a.seq")
    finally:
        engine.dispose()
    assert all(r["occurred_at"] == r["features_as_of"] == r["scored_at"] for r in rows)
    assert [r["occurred_at"] for r in rows] == sorted(r["occurred_at"] for r in rows)


def test_seeding_twice_is_byte_identical(seeded, data_dir, tmp_path):
    second = tmp_path / "second.db"
    seed_database(second, data_dir=data_dir)
    a, b = sqlite3.connect(seeded[0]), sqlite3.connect(second)
    try:
        for sql in ("SELECT * FROM decisions ORDER BY decision_id", "SELECT * FROM audit_events ORDER BY seq"):
            assert a.execute(sql).fetchall() == b.execute(sql).fetchall()
        hashes = "SELECT event_hash FROM audit_events ORDER BY seq"
        assert a.execute(hashes).fetchall() == b.execute(hashes).fetchall()
    finally:
        a.close()
        b.close()


def test_seeded_world_has_nothing_at_or_after_the_demo_clock(seeded):
    engine = get_engine(seeded[0])
    clock = utc_iso(DEMO_CLOCK)
    try:
        assert _rows(engine, "SELECT COUNT(*) AS n FROM order_events WHERE occurred_at >= ?", clock)[0]["n"] == 0
        assert _rows(engine, "SELECT COUNT(*) AS n FROM orders WHERE placed_at >= ?", clock)[0]["n"] == 0
        assert _count(engine, "order_labels") == 0 and _count(engine, "sim_ground_truth") == 0
    finally:
        engine.dispose()


def test_seeding_finishes_within_budget(seeded):
    assert seeded[2] < SEED_BUDGET_S


def test_governance_rows(seeded, cfg, models):
    engine = get_engine(seeded[0])
    try:
        policy = _rows(engine, "SELECT * FROM policy_versions")
        registry_rows = {r["model_name"]: r for r in _rows(engine, "SELECT * FROM model_registry")}
    finally:
        engine.dispose()
    assert [(p["policy_version"], p["config_sha256"]) for p in policy] == [(cfg.policy.version, cfg.config_sha256)]
    import hashlib
    assert hashlib.sha256(policy[0]["config_toml"].replace("\r\n", "\n").encode("utf-8")).hexdigest() == cfg.config_sha256
    assert registry_rows["ABUSE"]["model_version"] == models.bundles["abuse"]["model_version"]
    assert registry_rows["RETURN"]["artifact_sha256"] == models.bundles["return"]["sha256"]
    assert registry_rows["ABUSE"]["calibration_method"] == "SIGMOID"


# ── the chain ────────────────────────────────────────────────────────────────
def test_chain_verifies_on_a_seeded_database(engine):
    assert verify_chain(engine) == (True, SEEDED_DECISIONS, None)


def test_edited_payload_breaks_the_chain_at_exactly_that_seq(engine):
    target = 117
    engine.dispose()
    conn = sqlite3.connect(engine.url.database)
    try:
        conn.execute("DROP TRIGGER audit_no_update")
        payload = json.loads(conn.execute("SELECT payload_json FROM audit_events WHERE seq = ?", (target,)).fetchone()[0])
        payload["selected_action"] = "ALLOW" if payload["selected_action"] != "ALLOW" else "BLOCK"
        conn.execute("UPDATE audit_events SET payload_json = ? WHERE seq = ?",
                     (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), target))
        conn.commit()
    finally:
        conn.close()
    assert verify_chain(engine) == (False, target, target)


def test_audit_rows_cannot_be_updated_or_deleted(engine):
    with read_connection(engine) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE audit_events SET actor_id = 'x' WHERE seq = 1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM audit_events WHERE seq = 1")


# ── scoring ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def offline_demos(world, models, cfg):
    return {d.order_id: d for d in score_demos(models.bundles, cfg, {t: world[t] for t in WORLD_TABLES})}


def test_demos_score_to_their_actions_with_the_offline_probabilities(service, offline_demos):
    for order_id, request in _requests().items():
        response = service.score(request, "DEMO")
        offline = offline_demos[order_id]
        assert response.policy.selected_action is DEMO_ACTIONS[order_id], order_id
        assert response.scores.p_abuse == pytest.approx(offline.p_abuse, abs=1e-9)
        assert response.scores.p_return == pytest.approx(offline.p_return, abs=1e-9)
        assert response.policy.selected_action is offline.decision.selected_action
        assert not response.degraded_mode and not response.idempotent_replay


def test_p1_demo_features_are_identical_offline_and_through_the_service(service, engine, offline_demos):
    for order_id, request in _requests().items():
        service.score(request, "DEMO")
        stored = json.loads(_rows(engine, "SELECT features_json FROM decisions WHERE order_id = ?",
                                  order_id)[0]["features_json"])
        offline = {k: (v.item() if hasattr(v, "item") else v) for k, v in offline_demos[order_id].features.items()}
        assert stored == offline, order_id


def test_demo_status_and_recorded_rows(service, engine):
    responses = {oid: service.score(r, "DEMO") for oid, r in _requests().items()}
    assert responses["ORD-DEMO-003"].status == "PENDING_REVIEW"
    assert responses["ORD-DEMO-002"].status == responses["ORD-DEMO-001"].status == "AUTO_APPLIED"
    rows = {r["order_id"]: r for r in _rows(engine, "SELECT * FROM decisions WHERE source = 'DEMO'")}
    assert set(rows) == set(DEMO_ACTIONS)
    for oid, row in rows.items():
        assert row["recommended_action"] == row["current_action"] == DEMO_ACTIONS[oid].value
        assert row["scored_at"] == utc_iso(DEMO_CLOCK)
        assert row["latest_audit_event_id"] == responses[oid].audit_event_id
    orders = {r["order_id"]: r for r in _rows(engine, "SELECT * FROM orders WHERE source = 'DEMO'")}
    assert orders["ORD-DEMO-002"]["order_value_inr"] == pytest.approx(24000.0)
    assert verify_chain(engine) == (True, SEEDED_DECISIONS + 3, None)


def test_demo_2_device_reason_renders_the_confirmed_counts(service):
    response = service.score(_requests()["ORD-DEMO-002"], "DEMO")
    text = next(r.reviewer_text for r in response.reasons if r.code == "GRAPH_DEVICE_CONFIRMED_LINK")
    assert text.startswith("This device was used by 3 accounts later confirmed for return abuse, most recently ")


def _decision_content(engine) -> dict:
    ignore = {"decision_id", "latest_audit_event_id"}
    return {r["order_id"]: {k: v for k, v in r.items() if k not in ignore}
            for r in _rows(engine, "SELECT * FROM decisions WHERE source = 'DEMO'")}


def test_scoring_is_order_independent_across_all_permutations(seeded, tmp_path, cfg, models, builder):
    """Frozen history: Demo 3 scores the same whether it is scored first or last (P14 amendment)."""
    requests = _requests()
    outcomes = []
    for i, order in enumerate(itertools.permutations(requests)):
        engine = _fresh(seeded, tmp_path, f"perm{i}.db")
        try:
            svc = ScoringService(engine, cfg, models, builder)
            for oid in order:
                svc.score(requests[oid], "DEMO")
            outcomes.append(_decision_content(engine))
        finally:
            engine.dispose()
    assert len(outcomes) == 6
    assert all(o == outcomes[0] for o in outcomes[1:])


def test_idempotent_replay_returns_the_same_decision_and_writes_nothing(service, engine):
    request = _requests()["ORD-DEMO-002"]
    first = service.score(request, "DEMO")
    events = _count(engine, "audit_events")
    second = service.score(request, "DEMO")
    assert second.idempotent_replay and second.decision_id == first.decision_id
    assert second.model_dump(exclude={"idempotent_replay"}) == first.model_dump(exclude={"idempotent_replay"})
    assert _count(engine, "audit_events") == events


def test_replay_accepts_the_same_payload_in_another_timezone(service):
    request = _requests()["ORD-DEMO-001"]
    first = service.score(request, "DEMO")
    utc = request.model_copy(update={"placed_at": request.placed_at.astimezone(tz=__import__("datetime").timezone.utc)})
    assert service.score(utc, "DEMO").decision_id == first.decision_id


def test_same_order_id_with_a_different_payload_conflicts(service):
    request = _requests()["ORD-DEMO-003"]
    service.score(request, "DEMO")
    with pytest.raises(Conflict, match="different payload"):
        service.score(request.model_copy(update={"discount_pct": 10.0}), "DEMO")


def test_a_failed_audit_write_leaves_no_decision(service, engine, monkeypatch):
    import sentinel.api.services.scoring as scoring

    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected audit failure")

    monkeypatch.setattr(scoring, "append_event", fail)
    before = (_count(engine, "decisions"), _count(engine, "orders"), _count(engine, "audit_events"))
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        service.score(_requests()["ORD-DEMO-003"], "DEMO")
    assert (_count(engine, "decisions"), _count(engine, "orders"), _count(engine, "audit_events")) == before
    assert not _rows(engine, "SELECT 1 FROM decisions WHERE order_id = 'ORD-DEMO-003'")


def test_placed_at_after_the_demo_clock_is_rejected(service):
    request = _requests()["ORD-DEMO-001"].model_copy(update={"placed_at": DEMO_CLOCK + timedelta(seconds=1)})
    with pytest.raises(RequestRejected, match="demo clock"):
        service.score(request, "DEMO")


def test_placed_at_before_the_end_of_the_frozen_history_is_rejected(service):
    request = _requests()["ORD-DEMO-001"].model_copy(
        update={"order_id": "ORD-LATE-001", "placed_at": DEMO_CLOCK - timedelta(days=30)})
    with pytest.raises(RequestRejected, match="frozen scoring history"):
        service.score(request, "LIVE")


def test_unknown_account_is_not_found(service):
    """Architect decision 1.3 (Phase 7): an unknown account is NotFound (-> 404), never scored."""
    from sentinel.api.services.errors import UnknownAccount
    request = _requests()["ORD-DEMO-001"].model_copy(update={"order_id": "ORD-NEW-001", "account_id": "ACC-NOBODY"})
    with pytest.raises(UnknownAccount, match="unknown account"):
        service.score(request, "LIVE")


def test_scoring_a_historical_order_id_conflicts(service, engine):
    history_id = _rows(engine, "SELECT o.order_id FROM orders o LEFT JOIN decisions d USING (order_id) "
                               "WHERE d.order_id IS NULL AND o.source = 'HISTORY' LIMIT 1")[0]["order_id"]
    request = _requests()["ORD-DEMO-001"].model_copy(update={"order_id": history_id})
    with pytest.raises(Conflict, match="never scored"):
        service.score(request, "LIVE")


def test_live_order_with_a_new_identifier_is_recorded_masked(service, engine):
    request = _requests()["ORD-DEMO-001"].model_copy(update={"order_id": "ORD-LIVE-001", "device_id": "c0ffee" * 5 + "ab"})
    response = service.score(request, "LIVE")
    assert not response.degraded_mode
    label = _rows(engine, "SELECT display_label FROM identifiers WHERE identifier_id = ?", request.device_id)[0]
    from sentinel.data.generator import display_label
    assert label["display_label"] == display_label("DEVICE", request.device_id) == "Device ••eeab"
    assert _rows(engine, "SELECT source FROM decisions WHERE order_id = 'ORD-LIVE-001'")[0]["source"] == "LIVE"


def test_history_replay_excludes_live_orders(service, engine, cfg):
    """A restart must score exactly as before: live orders never enter the frozen history."""
    service.score(_requests()["ORD-DEMO-002"], "DEMO")
    history = load_history(engine)
    assert "ORD-DEMO-002" not in set(history["orders"]["order_id"])


# ── degraded mode (G6, #14) ──────────────────────────────────────────────────
def _assert_degraded(response, engine, expected_action):
    assert response.degraded_mode
    assert response.scores.p_abuse is None and response.scores.p_return is None
    assert response.scores.p_abuse_without_graph_evidence is None
    assert response.policy.costs == [] and response.policy.cost_optimal_action is None
    assert response.policy.selected_rule == "DEGRADED_MODE_FALLBACK"
    assert response.policy.selected_action is expected_action
    assert response.policy.selected_action is not Action.BLOCK
    assert response.reasons == []
    g6 = next(g for g in response.policy.guardrails if g.guardrail_id == "G6")
    assert g6.effect == "FALLBACK" and "Degraded mode (" in g6.detail
    payload = json.loads(_rows(engine, "SELECT payload_json FROM audit_events WHERE event_id = ?",
                               response.audit_event_id)[0]["payload_json"])
    assert payload["degraded_mode"] is True and payload["p_abuse"] is None and payload["candidate_actions"] == []
    assert payload["cost_optimal_action"] is None
    assert verify_chain(engine)[0]


@pytest.mark.parametrize("stage", ["features", "predict"])
def test_fault_injection_yields_a_degraded_decision(service, engine, stage):
    def fault(name):
        if name == stage:
            raise RuntimeError(f"injected {stage} fault")
    service.fault_hook = fault
    requests = _requests()
    _assert_degraded(service.score(requests["ORD-DEMO-002"], "DEMO"), engine, Action.MANUAL_REVIEW)   # ₹24,000
    _assert_degraded(service.score(requests["ORD-DEMO-001"], "DEMO"), engine, Action.ALLOW)           # ₹4,500


def test_model_load_failure_serves_degraded_decisions(engine, cfg, tmp_path):
    service = ScoringService.start(engine, artifacts_dir=tmp_path / "no-artifacts", policy_config=cfg)
    assert service.models is None and "model loading failed" in service.startup_error
    response = service.score(_requests()["ORD-DEMO-003"], "DEMO")                                        # ₹12,000
    _assert_degraded(response, engine, Action.MANUAL_REVIEW)
    row = _rows(engine, "SELECT * FROM decisions WHERE order_id = 'ORD-DEMO-003'")[0]
    assert row["degraded_mode"] == 1 and row["p_abuse"] is None and row["cost_optimal_action"] is None
    assert row["abuse_model_version"]                  # versions still recorded, from the seeded registry


def test_degraded_replay_is_idempotent(service, engine):
    service.fault_hook = lambda name: (_ for _ in ()).throw(RuntimeError("down"))
    first = service.score(_requests()["ORD-DEMO-002"], "DEMO")
    service.fault_hook = None
    second = service.score(_requests()["ORD-DEMO-002"], "DEMO")
    assert second.idempotent_replay and second.degraded_mode and second.decision_id == first.decision_id


# ── reviewer actions ─────────────────────────────────────────────────────────
class _Clock:
    def __init__(self):
        self.now = DEMO_CLOCK

    def __call__(self):
        self.now += timedelta(minutes=3)
        return self.now


@pytest.fixture
def scored(service, engine):
    responses = {oid: service.score(r, "DEMO") for oid, r in _requests().items()}
    return responses, ReviewService(engine, clock=_Clock())


def _override(new, expected, category="CUSTOMER_VERIFIED",
              text="Customer confirmed prior claim was a courier error; offering prepaid."):
    return OverrideRequest(new_action=new, reason_category=category, reason_text=text, expected_current_action=expected)


def test_override_writes_an_event_and_preserves_the_recommendation(scored, engine):
    responses, review = scored
    events = _count(engine, "audit_events")
    result = review.apply_override("ORD-DEMO-003", _override(Action.PREPAID_ONLY, Action.MANUAL_REVIEW), "reviewer-placeholder-01")
    assert _count(engine, "audit_events") == events + 1
    row = _rows(engine, "SELECT * FROM decisions WHERE order_id = 'ORD-DEMO-003'")[0]
    assert row["recommended_action"] == "MANUAL_REVIEW" and row["current_action"] == "PREPAID_ONLY"
    assert row["status"] == "OVERRIDDEN" and row["latest_audit_event_id"] == result.audit_event_id
    assert (result.original_recommendation, result.previous_action, result.new_action) == \
        (Action.MANUAL_REVIEW, Action.MANUAL_REVIEW, Action.PREPAID_ONLY)
    assert result.warnings == []
    payload = json.loads(_rows(engine, "SELECT payload_json FROM audit_events WHERE event_id = ?",
                               result.audit_event_id)[0]["payload_json"])
    created = json.loads(_rows(engine, "SELECT payload_json FROM audit_events WHERE event_id = ?",
                               responses["ORD-DEMO-003"].audit_event_id)[0]["payload_json"])
    assert payload["event_type"] == "OVERRIDE_APPLIED" and payload["actor"] == {"type": "REVIEWER", "id": "reviewer-placeholder-01"}
    # self-contained: the decision's scores, costs, versions and graph summary are repeated
    for key in ("p_abuse", "p_return", "candidate_actions", "model_versions", "graph_summary", "policy_config_sha256",
                "cost_optimal_action", "selected_action", "policy_rule"):
        assert payload[key] == created[key], key
    assert payload["override"]["reason_category"] == "CUSTOMER_VERIFIED"
    assert payload["override"]["guardrail_conflicts"] == []


def test_stale_expected_action_conflicts(scored):
    _, review = scored
    with pytest.raises(Conflict, match="expected current action"):
        review.apply_override("ORD-DEMO-003", _override(Action.ALLOW, Action.ALLOW), "reviewer-placeholder-01")


def test_block_without_corroboration_needs_independent_evidence(scored, engine):
    """Demo 1 has no counted signal, so G2 was not satisfied."""
    _, review = scored
    with pytest.raises(RequestRejected, match="INDEPENDENT_EVIDENCE_OF_ABUSE"):
        review.apply_override("ORD-DEMO-001", _override(Action.BLOCK, Action.ALLOW), "reviewer-placeholder-01")
    result = review.apply_override(
        "ORD-DEMO-001", _override(Action.BLOCK, Action.ALLOW, "INDEPENDENT_EVIDENCE_OF_ABUSE",
                                  "Warehouse photo evidence shows a swapped item on the prior order."),
        "reviewer-placeholder-01")
    assert result.warnings == [G2_WARNING]
    payload = json.loads(_rows(engine, "SELECT payload_json FROM audit_events WHERE event_id = ?",
                               result.audit_event_id)[0]["payload_json"])
    assert payload["override"]["guardrail_conflicts"] == ["G2"]


def test_block_with_corroboration_records_no_conflict(scored):
    """Demo 3 has DEVICE and ACCOUNT_CLAIMS counted, so G2 was satisfied (BLOCK was removed by G3 only)."""
    _, review = scored
    result = review.apply_override("ORD-DEMO-003", _override(Action.BLOCK, Action.MANUAL_REVIEW,
                                                             "OTHER", "Reviewer judgement after a phone call."),
                                   "reviewer-placeholder-01")
    assert result.warnings == []


def test_chained_overrides(scored, engine):
    _, review = scored
    review.apply_override("ORD-DEMO-003", _override(Action.PREPAID_ONLY, Action.MANUAL_REVIEW), "reviewer-placeholder-01")
    second = review.apply_override("ORD-DEMO-003", _override(Action.ALLOW, Action.PREPAID_ONLY, "POLICY_EXCEPTION",
                                                             "Escalated; allowing under a policy exception."),
                                   "reviewer-placeholder-02")
    assert (second.previous_action, second.new_action, second.original_recommendation) == \
        (Action.PREPAID_ONLY, Action.ALLOW, Action.MANUAL_REVIEW)
    history = _rows(engine, "SELECT event_type, previous_action, new_action FROM audit_events "
                            "WHERE order_id = 'ORD-DEMO-003' ORDER BY seq")
    assert history == [{"event_type": "DECISION_CREATED", "previous_action": None, "new_action": "MANUAL_REVIEW"},
                       {"event_type": "OVERRIDE_APPLIED", "previous_action": "MANUAL_REVIEW", "new_action": "PREPAID_ONLY"},
                       {"event_type": "OVERRIDE_APPLIED", "previous_action": "PREPAID_ONLY", "new_action": "ALLOW"}]


def test_appeal_references_are_sequential_and_open_the_appeal(scored, engine):
    _, review = scored
    first = review.open_appeal("ORD-DEMO-002", AppealRequest(channel="EMAIL", note="Customer disputes the block."), "support-01")
    second = review.open_appeal("ORD-DEMO-001", AppealRequest(channel="CUSTOMER_SUPPORT", note="Asked why it was held."), "support-01")
    assert (first.appeal_reference, second.appeal_reference) == ("APL-2026-000001", "APL-2026-000002")
    row = _rows(engine, "SELECT status, current_action, latest_audit_event_id FROM decisions WHERE order_id = 'ORD-DEMO-002'")[0]
    assert row == {"status": "APPEAL_OPEN", "current_action": "BLOCK", "latest_audit_event_id": first.audit_event_id}
    payload = json.loads(_rows(engine, "SELECT payload_json FROM audit_events WHERE event_id = ?",
                               first.audit_event_id)[0]["payload_json"])
    assert payload["appeal"] == {"appeal_reference": "APL-2026-000001", "channel": "EMAIL",
                                 "note": "Customer disputes the block.", "status": "OPEN"}
    assert payload["previous_action"] == payload["new_action"] == "BLOCK"
    with pytest.raises(Conflict, match="already open"):
        review.open_appeal("ORD-DEMO-002", AppealRequest(channel="EMAIL", note="Second attempt, same order."), "support-01")


def test_review_of_an_unknown_order_is_not_found(scored):
    _, review = scored
    with pytest.raises(NotFound):
        review.apply_override("ORD-NOPE-001", _override(Action.ALLOW, Action.ALLOW), "reviewer-placeholder-01")


def test_chain_verifies_after_every_kind_of_event(scored, engine):
    _, review = scored
    review.apply_override("ORD-DEMO-003", _override(Action.PREPAID_ONLY, Action.MANUAL_REVIEW), "reviewer-placeholder-01")
    review.apply_override("ORD-DEMO-003", _override(Action.ALLOW, Action.PREPAID_ONLY), "reviewer-placeholder-01")
    review.apply_override("ORD-DEMO-001", _override(Action.BLOCK, Action.ALLOW, "INDEPENDENT_EVIDENCE_OF_ABUSE",
                                                    "Warehouse photo evidence shows a swapped item."), "r-02")
    review.open_appeal("ORD-DEMO-001", AppealRequest(channel="EMAIL", note="Customer disputes the block."), "support-01")
    seeded_id = _rows(engine, "SELECT order_id, current_action FROM decisions WHERE source = 'BACKTEST_REPLAY' LIMIT 1")[0]
    review.apply_override(seeded_id["order_id"], _override(Action.MANUAL_REVIEW, Action(seeded_id["current_action"])), "r-03")
    assert verify_chain(engine) == (True, SEEDED_DECISIONS + 3 + 5, None)


# ── reset on Windows ─────────────────────────────────────────────────────────
def test_reset_demo_twice_in_a_row(seeded, data_dir, tmp_path, cfg, models, builder):
    path = tmp_path / "reset.db"
    shutil.copy(seeded[0], path)
    engine = get_engine(path)
    ScoringService(engine, cfg, models, builder).score(_requests()["ORD-DEMO-001"], "DEMO")   # holds a pooled connection
    engine.dispose()                                    # what the API's reset route must do before resetting
    for _ in range(2):
        report = reset_demo(path, demo_mode=True, data_dir=data_dir)
        assert report.by_source == {"BACKTEST_REPLAY": SEEDED_DECISIONS}
    assert not path.with_name(path.name + "-wal").exists()


def test_reset_demo_refuses_when_demo_mode_is_off(tmp_path, data_dir):
    with pytest.raises(DemoModeOff):
        reset_demo(tmp_path / "never.db", demo_mode=False, data_dir=data_dir)
    assert not (tmp_path / "never.db").exists()


# ── Phase 7 Part 1: point-in-time graph evidence (#32) ───────────────────────
HARD_NEGATIVE_REASONS = {"HOUSEHOLD": "HOUSEHOLD_PATTERN", "OFFICE_HOSTEL_PG": "MULTI_TENANT_ADDRESS"}
IDENTIFIER_COLUMNS = (("DEVICE", "DEV", "device_id"), ("ADDRESS", "ADR", "address_id"),
                      ("PAYMENT_TOKEN", "TOK", "payment_token_id"))


def _seeded_decisions(seeded) -> list[dict]:
    engine = get_engine(seeded[0])
    try:
        return _rows(engine, "SELECT d.order_id, d.features_as_of, d.discounted_links_json, d.graph_payload_json, "
                             "d.reasons_json, d.graph_summary_json, o.account_id, o.device_id FROM decisions d "
                             "JOIN orders o USING (order_id)")
    finally:
        engine.dispose()


def _utc(text: str):
    from sentinel.db.models import parse_utc
    return parse_utc(text.replace("Z", "+00:00"))


def test_seeded_hard_negative_orders_show_their_discounted_link(seeded, data_dir):
    """Ground truth is read by the test only, to find the hard negatives among the 250."""
    import pandas as pd

    from sentinel.data.generator import OUTPUT_FILES
    truth = pd.read_parquet(data_dir / OUTPUT_FILES["sim_ground_truth"])
    archetype = dict(zip(truth["account_id"], truth["archetype"]))
    checked = 0
    for d in _seeded_decisions(seeded):
        expected = HARD_NEGATIVE_REASONS.get(archetype.get(d["account_id"]))
        links = json.loads(d["discounted_links_json"])
        if expected is None or expected not in {link["reason"] for link in links}:
            continue
        checked += 1
        assert links == json.loads(d["graph_summary_json"])["discounted_links"]
        assert "MITIGATING_DISCOUNTED_LINKS" in {r["code"] for r in json.loads(d["reasons_json"])}
        dashed = [e for e in json.loads(d["graph_payload_json"])["edges"] if e["discount_reason"] == expected]
        assert dashed and all(not e["counted_as_evidence"] for e in dashed)
    assert checked >= 5                                # measured: 12 household + 5 office/hostel/PG


def test_every_seeded_decision_has_links_and_a_point_in_time_graph(seeded):
    for d in _seeded_decisions(seeded):
        assert d["discounted_links_json"] is not None and d["graph_payload_json"] is not None
        graph = json.loads(d["graph_payload_json"])
        assert _utc(graph["as_of"]) == _utc(d["features_as_of"])
        assert 2 <= len(graph["nodes"]) <= 40


def test_seeded_graphs_contain_nothing_first_seen_at_or_after_t0(seeded):
    """Every linked account, linked order, identifier and edge in a seeded graph existed strictly before t0.

    Since #35 a graph can also draw identifiers that are not the order's own - the hop that reaches an
    account two hops out, or a token the account used on an earlier order - so every identifier node is
    resolved against the identifiers table and every edge that is not one of the order's own must be
    backed by an order placed before t0.
    """
    from sentinel.api.services.graph_view import identifier_node_id
    engine = get_engine(seeded[0])
    column_of = {kind: col for kind, _, col in IDENTIFIER_COLUMNS}
    try:
        with read_connection(engine) as conn:
            known = {identifier_node_id(r["kind"], f"{NODE_PREFIX[r['kind']]}:{r['identifier_id']}"):
                     (r["kind"], r["identifier_id"])
                     for r in conn.execute("SELECT identifier_id, kind FROM identifiers")}
            for d in _seeded_decisions(seeded):
                t0 = d["features_as_of"]
                graph = json.loads(d["graph_payload_json"])
                order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (d["order_id"],)).fetchone()
                own = {identifier_node_id(kind, f"{prefix}:{order[col]}")
                       for kind, prefix, col in IDENTIFIER_COLUMNS if order[col] is not None}
                current = {f"ACC:{d['account_id']}", f"ORD:{d['order_id']}"}
                for node in graph["nodes"]:
                    if node["id"] in current:
                        continue
                    if node["kind"] == "ACCOUNT":
                        acc = node["id"][4:]
                        assert conn.execute("SELECT created_at < ? FROM accounts WHERE account_id = ?",
                                            (t0, acc)).fetchone()[0] == 1
                        assert conn.execute("SELECT COUNT(*) FROM orders WHERE account_id = ? AND placed_at < ?",
                                            (acc, t0)).fetchone()[0] >= 1
                    elif node["kind"] == "ORDER":
                        placed = conn.execute("SELECT placed_at FROM orders WHERE order_id = ?",
                                              (node["id"][4:],)).fetchone()[0]
                        assert placed < t0 and "RECENT_24H" in node["flags"]
                    else:
                        kind, _ = known[node["id"]]     # resolves to a real identifier of the same kind
                        assert kind == node["kind"], (d["order_id"], node["id"])
                for edge in graph["edges"]:
                    if edge["kind"] == "PLACED_BY":
                        continue                       # order nodes are checked above
                    if edge["source"] in current and edge["target"] in own:
                        continue                       # the order's own edges are at t0 by construction
                    kind, identifier_id = known[edge["target"]]
                    col = column_of[kind]
                    n = conn.execute(f"SELECT COUNT(*) FROM orders WHERE account_id = ? AND {col} = ? "
                                     "AND placed_at < ?", (edge["source"][4:], identifier_id, t0)).fetchone()[0]
                    assert n >= 1, (d["order_id"], edge["id"])
    finally:
        engine.dispose()


def test_live_decisions_store_links_and_graph_from_the_frozen_builder(service, engine):
    for oid, request in _requests().items():
        response = service.score(request, "DEMO")
        row = _rows(engine, "SELECT discounted_links_json, graph_payload_json FROM decisions WHERE order_id = ?", oid)[0]
        links = json.loads(row["discounted_links_json"])
        assert links == [link.model_dump(mode="json") for link in response.graph_summary.discounted_links]
        graph = json.loads(row["graph_payload_json"])
        assert _utc(graph["as_of"]) == request.placed_at
        assert 2 < len(graph["nodes"]) <= 40
    demo1 = _rows(engine, "SELECT discounted_links_json FROM decisions WHERE order_id = 'ORD-DEMO-001'")[0]
    assert [link["reason"] for link in json.loads(demo1["discounted_links_json"])] == ["HOUSEHOLD_PATTERN"]
    demo2 = _rows(engine, "SELECT graph_payload_json FROM decisions WHERE order_id = 'ORD-DEMO-002'")[0]
    assert sum(n["state"] == "CONFIRMED_ABUSE" for n in json.loads(demo2["graph_payload_json"])["nodes"]) == 3


def test_degraded_decisions_store_no_graph(service, engine):
    def fail(stage):
        raise RuntimeError("injected")

    service.fault_hook = fail
    service.score(_requests()["ORD-DEMO-003"], "DEMO")
    row = _rows(engine, "SELECT discounted_links_json, graph_payload_json FROM decisions "
                        "WHERE order_id = 'ORD-DEMO-003'")[0]
    assert row["discounted_links_json"] == "[]" and row["graph_payload_json"] is None


@pytest.mark.parametrize("column", ["discounted_links_json", "graph_payload_json"])
def test_captured_graph_evidence_is_immutable(engine, column):
    with read_connection(engine) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(f"UPDATE decisions SET {column} = '[]' WHERE rowid = 1")


# ── Phase 8 brief 1.1: the graph agrees with the numbers printed beside it ────
def _device_confirmed_nodes(graph: dict, device_node: str) -> set[str]:
    """Confirmed-abuse account nodes reachable through THIS order's device, read from the payload only.
    The account's earlier devices and tokens can also appear (they carry real links), so the device node is
    identified from the order's own device id rather than by adjacency to the current account."""
    confirmed = {n["id"] for n in graph["nodes"] if n["kind"] == "ACCOUNT" and n["state"] == "CONFIRMED_ABUSE"}
    return {e["source"] for e in graph["edges"] if e["target"] == device_node and e["source"] in confirmed}


def _payload_counts(graph: dict, device_node: str, order_id: str) -> tuple[int, int]:
    linked_orders = [n for n in graph["nodes"] if n["kind"] == "ORDER" and n["id"] != f"ORD:{order_id}"]
    return len(linked_orders), len(_device_confirmed_nodes(graph, device_node))


def test_every_seeded_graph_draws_every_counted_linked_order_and_confirmed_device_peer(seeded, world, cfg):
    """1.1: for every seeded decision, the 24 h order nodes equal linked_orders_24h and the confirmed
    accounts reachable through the device equal device_confirmed_peer_count. Recomputed from one
    chronological replay, exactly as seeding captured them."""
    from sentinel.api.services.graph_view import build_graph_payload
    from sentinel.features.graph_features import analyse
    from sentinel.features.graph_state import from_micros

    rows = {d["order_id"]: d for d in _seeded_decisions(seeded)}
    builder = FeatureBuilder({t: world[t] for t in WORLD_TABLES}, cfg)
    seen = with_orders = with_peers = 0
    for q, t0 in builder.iter_points_in_time(list(rows)):
        analysis = analyse(builder.state, q, t0)
        payload = build_graph_payload(builder.ego_view(q, t0), q, t0, from_micros(t0))
        graph = payload.model_dump(mode="json")
        device = identifier_node_id("DEVICE", node_id("DEVICE", dict(q.identifiers)["DEVICE"]))
        orders_shown, peers_shown = _payload_counts(graph, device, q.order_id)
        assert payload.linked_orders_24h_shown == orders_shown, q.order_id
        assert payload.confirmed_peers_shown == peers_shown, q.order_id
        linked = int(analysis.features["linked_orders_24h"])
        peers = int(analysis.evidence["device_confirmed_peer_count"])
        assert int(json.loads(rows[q.order_id]["graph_summary_json"])["linked_orders_24h"]) == linked
        if payload.truncated:                            # the *_shown fields then state what is drawn
            assert orders_shown <= linked and peers_shown <= peers
        else:
            assert orders_shown == linked, q.order_id
            assert peers_shown == peers, q.order_id
        seen += 1
        with_orders += linked > 0
        with_peers += peers > 0
    assert seen == SEEDED_DECISIONS
    assert with_orders >= 1 and with_peers >= 1          # the assertion is not vacuous


def test_stored_seeded_graphs_report_the_counts_they_draw(seeded):
    """The payloads on disk (regenerated by seed-db) carry the same agreement."""
    for d in _seeded_decisions(seeded):
        graph = json.loads(d["graph_payload_json"])
        device = identifier_node_id("DEVICE", node_id("DEVICE", d["device_id"]))
        orders_shown, peers_shown = _payload_counts(graph, device, d["order_id"])
        assert graph["linked_orders_24h_shown"] == orders_shown
        assert graph["confirmed_peers_shown"] == peers_shown
        if not graph["truncated"]:
            assert graph["linked_orders_24h_shown"] == json.loads(d["graph_summary_json"])["linked_orders_24h"]


def test_demo_graphs_draw_every_counted_linked_order(service, engine):
    """Demo 2 shows all four of its linked 24 h orders, the fourth through a two-hop member (#24)."""
    for order_id, request in _requests().items():
        response = service.score(request, "DEMO")
        row = _rows(engine, "SELECT graph_payload_json FROM decisions WHERE order_id = ?", order_id)[0]
        graph = json.loads(row["graph_payload_json"])
        device = identifier_node_id("DEVICE", node_id("DEVICE", request.device_id))
        orders_shown, peers_shown = _payload_counts(graph, device, order_id)
        assert not graph["truncated"]
        assert graph["linked_orders_24h_shown"] == orders_shown == response.graph_summary.linked_orders_24h
        assert graph["confirmed_peers_shown"] == peers_shown
    demo2 = json.loads(_rows(engine, "SELECT graph_payload_json FROM decisions "
                                     "WHERE order_id = 'ORD-DEMO-002'")[0]["graph_payload_json"])
    assert demo2["linked_orders_24h_shown"] == 4 and demo2["confirmed_peers_shown"] == 3


# ── Phase 9 brief 1.8: ORDER nodes are drawn only for the 24-hour window ─────
def test_every_order_node_in_every_stored_graph_is_recent(seeded):
    """The legend can only say "Order placed in the last 24 h" if that is true of every ORDER node.

    An ORDER node exists in the payload because `linked_orders_24h` counted it (#32, #35), so the
    RECENT_24H flag is the graph builder restating what put the node there. This test is the licence
    for dropping the per-node badge: if it ever fails, the legend is wrong and the badge is load-bearing.
    """
    decisions = _seeded_decisions(seeded)
    assert len(decisions) == 250
    linked = current = 0
    for d in decisions:
        if d["graph_payload_json"] is None:
            continue
        for node in json.loads(d["graph_payload_json"])["nodes"]:
            if node["kind"] != "ORDER":
                continue
            if node["state"] == "CURRENT":
                # The order under review, drawn at the centre. It is the subject of the page, not
                # evidence about it, it is always this decision's own order, and it carries no flag at
                # all - so it never had a badge to drop and the legend's linked-order swatch is not
                # describing it. Measured over the seeded world: 250 of 250.
                current += 1
                assert node["id"] == f"ORD:{d['order_id']}"
                assert node["flags"] == [], (d["order_id"], node["flags"])
                continue
            linked += 1
            assert "RECENT_24H" in node["flags"], (d["order_id"], node["id"], node["flags"])
    assert linked > 0, "no linked ORDER node was drawn at all, so the check proves nothing"
    assert current == 250


def test_every_order_node_in_the_three_demo_graphs_is_recent(service, engine):
    """The same check on the payloads the demo actually shows (Demo 2 draws four of them)."""
    for oid in _requests():
        service.score(_requests()[oid], "DEMO")
    drawn = 0
    for oid in _requests():
        row = _rows(engine, "SELECT graph_payload_json FROM decisions WHERE order_id = ?", oid)[0]
        for node in json.loads(row["graph_payload_json"])["nodes"]:
            if node["kind"] != "ORDER":
                continue
            drawn += 1
            # The order being scored is the ORDER node at the centre and is not a linked order.
            if node["state"] == "CURRENT":
                continue
            assert "RECENT_24H" in node["flags"], (oid, node["id"], node["flags"])
    assert drawn > 0
