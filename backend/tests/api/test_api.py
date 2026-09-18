"""Phase 7: the HTTP API over a real seeded database (brief §G).

Self-contained: the world is generated in-process, written to a temporary data directory with its features,
seeded into a temporary database, and served by `create_app(db_path=...)` through TestClient (which runs the
lifespan). Nothing under backend/data is read or written. Reviewer time comes from an injected fixed clock.
"""
import json
import re
import shutil
import sqlite3
import statistics
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sentinel.api.main import create_app
from sentinel.api.services.checkout import CONFIRMED_MESSAGE, support_reference
from sentinel.api.services.graph_view import identifier_node_id
from sentinel.data.generator import write_outputs
from sentinel.db.seed import SEEDED_DECISIONS, seed_database
from sentinel.features.builder import build_tables
from sentinel.money import format_inr
from sentinel.settings import DEMO_CLOCK, INTERNAL_API_KEY

pytestmark = pytest.mark.slow

KEY = {"X-Internal-Key": INTERNAL_API_KEY}
I = "/api/v1/internal"
CHECKOUT = "/api/v1/public/checkout/decision"
DEMO_ACTIONS = {"ORD-DEMO-001": "ALLOW", "ORD-DEMO-002": "BLOCK", "ORD-DEMO-003": "MANUAL_REVIEW"}
DATA_NOTICE = ("Synthetic data is used to validate the architecture, policy behaviour, auditability, "
               "and coordinated-pattern detection. Real deployment would require merchant-specific "
               "historical data and prospective validation.")
LATENCY_P95_MS = 300.0


class FixedStepClock:
    def __init__(self):
        self.now = DEMO_CLOCK

    def __call__(self):
        self.now += timedelta(minutes=2)
        return self.now


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def data_dir(world, tmp_path_factory):
    path = tmp_path_factory.mktemp("api-data")
    write_outputs(world, path)
    features, policy = build_tables(world)
    features.to_parquet(path / "features.parquet", index=False)
    policy.to_parquet(path / "policy_inputs.parquet", index=False)
    return path


@pytest.fixture(scope="module")
def seeded_db(data_dir, tmp_path_factory):
    path = tmp_path_factory.mktemp("api-seed") / "sentinel.db"
    seed_database(path, data_dir=data_dir)
    return path


def _copy_db(seeded_db, tmp_path):
    target = tmp_path / "sentinel.db"
    shutil.copy(seeded_db, target)
    shutil.copy(seeded_db.with_name("demo_presets.json"), tmp_path / "demo_presets.json")
    return target


def _client(db, data_dir, demo_mode=True):
    return TestClient(create_app(db, demo_mode=demo_mode, data_dir=data_dir, clock=FixedStepClock()))


@pytest.fixture
def client(seeded_db, data_dir, tmp_path):
    with _client(_copy_db(seeded_db, tmp_path), data_dir) as c:
        yield c


@pytest.fixture(scope="module")
def shared(seeded_db, data_dir, tmp_path_factory):
    """One app for read-mostly tests; the three demos are scored once."""
    db = _copy_db(seeded_db, tmp_path_factory.mktemp("api-shared"))
    with _client(db, data_dir) as c:
        for p in c.get(f"{I}/demo/presets", headers=KEY).json():
            assert c.post(f"{I}/score-order", json=p, headers=KEY).status_code == 200
        yield c, db


def _presets(c) -> dict[str, dict]:
    return {p["order_id"]: p for p in c.get(f"{I}/demo/presets", headers=KEY).json()}


def _db_rows(db, sql, *args):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


# ── A. app shell ─────────────────────────────────────────────────────────────
def test_startup_fails_fast_without_the_database(tmp_path, data_dir):
    with pytest.raises(RuntimeError, match=re.escape("Database not found. Run: python -m sentinel.cli seed-db")):
        with _client(tmp_path / "missing.db", data_dir):
            pass


def test_no_cors_and_health_needs_no_key(shared):
    from starlette.middleware.cors import CORSMiddleware
    c, _ = shared
    assert all(m.cls is not CORSMiddleware for m in c.app.user_middleware)
    assert c.get("/health").status_code == 200


# ── auth ─────────────────────────────────────────────────────────────────────
INTERNAL_ROUTES = [
    ("POST", "/score-order"), ("GET", "/orders"), ("GET", "/orders/ORD-DEMO-001"),
    ("POST", "/orders/ORD-DEMO-001/override"), ("POST", "/orders/ORD-DEMO-001/appeal"),
    ("GET", "/audit-events"), ("GET", "/audit-events/verify"), ("GET", "/metrics"), ("GET", "/policy"),
    ("GET", "/demo/presets"), ("POST", "/demo/reset"),
]


@pytest.mark.parametrize("method,path", INTERNAL_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong-key"}], ids=["missing", "wrong"])
def test_every_internal_route_needs_the_key(shared, method, path, headers):
    c, _ = shared
    res = c.request(method, f"{I}{path}", headers=headers, json={})
    assert res.status_code == 401
    assert res.json() == {"detail": "Unauthorized"}


def test_internal_route_table_is_complete(shared):
    c, _ = shared
    spec = c.app.openapi()["paths"]
    internal = {(m.upper(), p[len(I):]) for p, ops in spec.items() if p.startswith(I) for m in ops}
    templated = {(m, re.sub(r"ORD-DEMO-001", "{order_id}", p)) for m, p in INTERNAL_ROUTES}
    assert internal == templated


def test_public_route_needs_no_key(shared):
    c, _ = shared
    assert c.post(CHECKOUT, json=_presets(c)["ORD-DEMO-001"]).status_code == 200


# ── no model endpoint ────────────────────────────────────────────────────────
def test_openapi_has_no_model_endpoint(shared):
    c, _ = shared
    paths = list(c.app.openapi()["paths"])
    assert not [p for p in paths if "predict" in p.lower() or "model" in p.lower()]
    assert [p for p in paths if "score" in p.lower()] == [f"{I}/score-order"]


# ── public safety ────────────────────────────────────────────────────────────
PUBLIC_KEYS = {"order_id", "outcome", "customer_message", "support_reference"}


def test_checkout_bodies_are_outcome_only(shared):
    c, _ = shared
    bodies = {oid: c.post(CHECKOUT, json=p).json() for oid, p in _presets(c).items()}
    for oid, body in bodies.items():
        assert set(body) <= PUBLIC_KEYS
        assert not re.search(r"\d", body["customer_message"].replace(body["support_reference"], ""))
        assert re.fullmatch(r"SUP-[0-9A-F]{8}", body["support_reference"])
    assert bodies["ORD-DEMO-001"]["outcome"] == "CONFIRMED"
    assert bodies["ORD-DEMO-002"]["outcome"] == "UNABLE_TO_PROCESS"
    assert bodies["ORD-DEMO-003"]["outcome"] == "CONFIRMED"


def test_allow_and_manual_review_bodies_are_identical_apart_from_ids(shared):
    c, _ = shared
    presets = _presets(c)
    allow, review = (c.post(CHECKOUT, json=presets[o]).content for o in ("ORD-DEMO-001", "ORD-DEMO-003"))
    a, r = json.loads(allow), json.loads(review)
    strip = lambda b: json.dumps({k: v for k, v in b.items() if k not in ("order_id", "support_reference")},  # noqa: E731
                                 sort_keys=True)
    assert strip(a) == strip(r)
    assert a["customer_message"] == r["customer_message"] == CONFIRMED_MESSAGE
    # byte-identical once the two id values are swapped in
    assert allow.replace(a["order_id"].encode(), b"X").replace(a["support_reference"].encode(), b"Y") == \
        review.replace(r["order_id"].encode(), b"X").replace(r["support_reference"].encode(), b"Y")


def test_support_reference_encodes_nothing_about_the_action(shared):
    c, db = shared
    body = c.post(CHECKOUT, json=_presets(c)["ORD-DEMO-002"]).json()
    decision_id = _db_rows(db, "SELECT decision_id FROM decisions WHERE order_id = 'ORD-DEMO-002'")[0]["decision_id"]
    assert body["support_reference"] == support_reference(decision_id)
    assert body["support_reference"] in body["customer_message"]


@pytest.mark.parametrize("case", ["bad_device", "unknown_account", "future", "conflict"])
def test_public_error_bodies_never_echo_request_fields(client, case):
    p = dict(_presets(client)["ORD-DEMO-001"])
    status = {"bad_device": 422, "unknown_account": 404, "future": 422, "conflict": 409}[case]
    if case == "bad_device":
        p["device_id"] = "someone@example.com"
    elif case == "unknown_account":
        p.update(order_id="ORD-PROBE-404", account_id="ACC-NOBODY-XYZ")
    elif case == "future":
        p.update(order_id="ORD-PROBE-FUT", placed_at=(DEMO_CLOCK + timedelta(days=1)).isoformat())
    else:
        assert client.post(CHECKOUT, json=p).status_code == 200
        p["discount_pct"] = 55
    res = client.post(CHECKOUT, json=p)
    assert res.status_code == status
    text = res.text
    for value in p.values():
        for leaf in ([value] if not isinstance(value, list) else [v for line in value for v in line.values()]):
            if isinstance(leaf, str) and len(leaf) >= 4:
                assert leaf not in text
    assert set(res.json()) == {"detail"}


def test_a_probe_row_is_written_per_call(client):
    presets = _presets(client)
    db = client.app.state.services.db_path
    for i in range(3):
        client.post(CHECKOUT, json=presets["ORD-DEMO-001"])
    client.post(CHECKOUT, json=presets["ORD-DEMO-003"])
    rows = _db_rows(db, "SELECT * FROM probe_events ORDER BY id")
    assert len(rows) == 4
    demo1 = [r for r in rows if r["device_id"] == presets["ORD-DEMO-001"]["device_id"]]
    assert [r["attempts_24h"] for r in demo1] == [1, 2, 3]
    assert [r["distinct_carts_24h"] for r in demo1] == [1, 1, 1]
    assert all(r["occurred_at"] > "2026-09-01T05:00:00" for r in rows)       # reviewer clock, demo world


# ── idempotency and errors over HTTP ─────────────────────────────────────────
def test_score_order_is_idempotent_over_http(client):
    p = _presets(client)["ORD-DEMO-002"]
    first = client.post(f"{I}/score-order", json=p, headers=KEY).json()
    second = client.post(f"{I}/score-order", json=p, headers=KEY).json()
    assert first["decision_id"] == second["decision_id"]
    assert (first["idempotent_replay"], second["idempotent_replay"]) == (False, True)
    changed = dict(p, discount_pct=12)
    assert client.post(f"{I}/score-order", json=changed, headers=KEY).status_code == 409


def test_unknown_order_is_404_with_a_neutral_message(shared):
    c, _ = shared
    for method, path in (("GET", "/orders/ORD-NOT-THERE"), ("POST", "/orders/ORD-NOT-THERE/override")):
        body = {"new_action": "ALLOW", "reason_category": "OTHER", "reason_text": "x" * 20,
                "expected_current_action": "ALLOW"}
        res = c.request(method, f"{I}{path}", headers=KEY, json=body)
        assert res.status_code == 404
        assert res.json() == {"detail": "Not found."}


def test_unknown_account_is_404(client):
    p = dict(_presets(client)["ORD-DEMO-001"], order_id="ORD-NEW-404", account_id="ACC-NOBODY-404")
    res = client.post(f"{I}/score-order", json=p, headers=KEY)
    assert res.status_code == 404 and res.json() == {"detail": "Not found."}


# ── override over HTTP ───────────────────────────────────────────────────────
def _override(c, order_id, new, expected, category="CUSTOMER_VERIFIED", text="Customer verified by phone call."):
    return c.post(f"{I}/orders/{order_id}/override", headers={**KEY, "X-Reviewer-Id": "reviewer-07"},
                  json={"new_action": new, "reason_category": category, "reason_text": text,
                        "expected_current_action": expected})


def test_override_over_http(client):
    p = _presets(client)["ORD-DEMO-003"]
    client.post(f"{I}/score-order", json=p, headers=KEY)
    assert _override(client, "ORD-DEMO-003", "PREPAID_ONLY", "ALLOW").status_code == 409     # stale
    assert _override(client, "ORD-DEMO-003", "PREPAID_ONLY", "MANUAL_REVIEW", text="too short").status_code == 422
    res = client.post(f"{I}/orders/ORD-DEMO-003/override", headers=KEY,
                      json={"new_action": "PREPAID_ONLY", "reason_category": "OTHER",
                            "expected_current_action": "MANUAL_REVIEW"})
    assert res.status_code == 422                                                          # missing reason
    res = _override(client, "ORD-DEMO-003", "PREPAID_ONLY", "MANUAL_REVIEW")
    assert res.status_code == 200
    body = res.json()
    assert (body["original_recommendation"], body["previous_action"], body["new_action"], body["reviewer_id"]) == \
        ("MANUAL_REVIEW", "MANUAL_REVIEW", "PREPAID_ONLY", "reviewer-07")
    assert body["overridden_at"].startswith("2026-09-01")                                   # demo reviewer clock
    # the customer now sees the override (§11 Demo 3)
    assert client.post(CHECKOUT, json=p).json()["outcome"] == "PREPAID_PAYMENT_REQUIRED"


def test_block_without_corroboration_needs_independent_evidence(client):
    """Demo 1 has G2 unmet: BLOCK with the wrong reason category is refused; with the right one, warned."""
    client.post(f"{I}/score-order", json=_presets(client)["ORD-DEMO-001"], headers=KEY)
    assert _override(client, "ORD-DEMO-001", "BLOCK", "ALLOW").status_code == 422
    res = _override(client, "ORD-DEMO-001", "BLOCK", "ALLOW", category="INDEPENDENT_EVIDENCE_OF_ABUSE")
    assert res.status_code == 200 and res.json()["warnings"]


def test_internal_validation_errors_do_not_echo_input(client):
    res = _override(client, "ORD-DEMO-001", "BLOCK", "ALLOW", text="short-secret")
    assert res.status_code == 422 and "short-secret" not in res.text


def test_appeal_opens_and_returns_its_audit_event(client):
    client.post(f"{I}/score-order", json=_presets(client)["ORD-DEMO-002"], headers=KEY)
    res = client.post(f"{I}/orders/ORD-DEMO-002/appeal", headers=KEY,
                      json={"channel": "EMAIL", "note": "Customer disputes the block."})
    assert res.status_code == 200
    event = res.json()
    assert event["event_type"] == "APPEAL_OPENED" and event["payload"]["appeal"]["status"] == "OPEN"
    detail = client.get(f"{I}/orders/ORD-DEMO-002", headers=KEY).json()
    assert detail["appeal_reference"] == event["payload"]["appeal"]["appeal_reference"] == "APL-2026-000001"
    assert client.post(f"{I}/orders/ORD-DEMO-002/appeal", headers=KEY,
                       json={"channel": "EMAIL", "note": "A second appeal."}).status_code == 409


# ── detail and graph ─────────────────────────────────────────────────────────
def _detail_orders(db) -> list[str]:
    seeded = [r["order_id"] for r in _db_rows(db, "SELECT order_id FROM decisions WHERE source = 'BACKTEST_REPLAY' "
                                                  "ORDER BY p_abuse DESC, order_id LIMIT 5")]
    return [*DEMO_ACTIONS, *seeded]


def _identifier_hashes(db) -> set[str]:
    return {r["identifier_id"] for r in _db_rows(db, "SELECT identifier_id FROM identifiers")}


def test_detail_graph_payloads(shared):
    c, db = shared
    hashes = _identifier_hashes(db)
    accounts = {r["account_id"] for r in _db_rows(db, "SELECT account_id FROM accounts")}
    for oid in _detail_orders(db):
        first = c.get(f"{I}/orders/{oid}", headers=KEY)
        second = c.get(f"{I}/orders/{oid}", headers=KEY)
        assert first.status_code == 200
        g1, g2 = first.json()["graph"], second.json()["graph"]
        assert json.dumps(g1, sort_keys=True).encode() == json.dumps(g2, sort_keys=True).encode()
        assert len(g1["nodes"]) <= 40
        t0 = first.json()["decision"]["features_as_of"]
        assert g1["as_of"] == t0
        current = first.json()["customer"]["account_id"]
        text = json.dumps(g1)
        assert not [h for h in hashes if h in text]                             # no identifier hash anywhere
        for node in g1["nodes"]:
            assert not re.search(r"[a-f0-9]{32}", node["label"])
            if node["kind"] == "ACCOUNT" and node["state"] != "CURRENT":
                assert node["label"] not in accounts and node["label"].startswith("Account ••")
        for edge in g1["edges"]:
            if not edge["counted_as_evidence"] and edge["source"] != f"ACC:{current}":
                assert edge["discount_reason"]
            if edge["discount_reason"]:
                assert not edge["counted_as_evidence"]
        # nothing first seen at or after t0: linked accounts and orders all precede it
        conn = sqlite3.connect(db)
        try:
            for node in g1["nodes"]:
                if node["state"] == "CURRENT" or node["kind"] not in ("ACCOUNT", "ORDER"):
                    continue
                if node["kind"] == "ORDER":
                    placed = conn.execute("SELECT placed_at FROM orders WHERE order_id = ?", (node["id"][4:],)).fetchone()[0]
                    assert placed < _db_rows(db, "SELECT features_as_of FROM decisions WHERE order_id = ?", oid)[0]["features_as_of"]
                else:
                    first_order = conn.execute("SELECT MIN(placed_at) FROM orders WHERE account_id = ?",
                                               (node["id"][4:],)).fetchone()[0]
                    assert first_order < _db_rows(db, "SELECT features_as_of FROM decisions WHERE order_id = ?", oid)[0]["features_as_of"]
        finally:
            conn.close()


def test_demo_2_graph_shows_the_ring(shared):
    c, db = shared
    g = c.get(f"{I}/orders/ORD-DEMO-002", headers=KEY).json()["graph"]
    assert sum(n["state"] == "CONFIRMED_ABUSE" for n in g["nodes"]) == 3
    assert {n["kind"] for n in g["nodes"]} >= {"ACCOUNT", "ORDER", "DEVICE", "ADDRESS", "PAYMENT_TOKEN"}
    order = _db_rows(db, "SELECT device_id FROM orders WHERE order_id = 'ORD-DEMO-002'")[0]
    device = identifier_node_id("DEVICE", f"DEV:{order['device_id']}")
    assert sum(e["target"] == device and e["counted_as_evidence"] for e in g["edges"]) >= 5


def test_detail_baselines_and_customer(shared):
    c, _ = shared
    d1 = c.get(f"{I}/orders/ORD-DEMO-001", headers=KEY).json()
    d2 = c.get(f"{I}/orders/ORD-DEMO-002", headers=KEY).json()
    rule = {d["order"]["order_id"]: {b["strategy"]: b["action"] for b in d["baselines"]} for d in (d1, d2)}
    assert rule["ORD-DEMO-001"]["RULE_BASED"] == "BLOCK"                     # §9.5 contrast
    assert rule["ORD-DEMO-002"]["RULE_BASED"] == "MANUAL_REVIEW"
    assert set(rule["ORD-DEMO-001"]) == {"FIXED_THRESHOLD", "RULE_BASED"}
    assert d1["customer"]["matured_return_rate"] == pytest.approx(28 / 48)
    assert d2["customer"]["clv_basis"] == "NEW_CUSTOMER_FLOOR"
    assert d1["audit_events"][0]["event_type"] == "DECISION_CREATED"
    assert d1["current_action"] == "ALLOW"


def test_detail_clv_is_what_the_policy_used(shared):
    """The recomputed CLV reproduces the recorded BLOCK genuine branch: (1 − p)·(margin + churn·CLV + support)."""
    from sentinel.policy.config import load_policy_config
    cfg = load_policy_config()
    c, db = shared
    for oid in _detail_orders(db):
        d = c.get(f"{I}/orders/{oid}", headers=KEY).json()
        p = d["decision"]["scores"]["p_abuse"]
        block = next(x for x in d["decision"]["policy"]["costs"] if x["action"] == "BLOCK")
        v, clv = d["order"]["order_value"]["inr"], d["customer"]["clv_used_by_policy"]["inr"]
        expected = (1 - p) * (cfg.economics.gross_margin_rate * v + cfg.block.genuine_clv_churn_rate * clv
                              + cfg.block.genuine_support_cost_inr)
        assert block["genuine_branch"]["inr"] == pytest.approx(expected, abs=0.02)


# ── queue ────────────────────────────────────────────────────────────────────
def _queue(c, **params):
    res = c.get(f"{I}/orders", headers=KEY, params={"limit": 200, **params})
    assert res.status_code == 200, res.text
    return res.json()


def _check_counts(q):
    counts = {a: 0 for a in ("ALLOW", "PREPAID_ONLY", "MANUAL_REVIEW", "BLOCK")}
    for item in q["items"]:
        counts[item["current_action"]] += 1
    if q["total"] <= 200:
        assert q["counts_by_action"] == counts
    assert sum(q["counts_by_action"].values()) == q["total"]


@pytest.mark.parametrize("params,check", [
    ({"action": "BLOCK"}, lambda i: i["current_action"] == "BLOCK"),
    ({"status": "PENDING_REVIEW"}, lambda i: i["status"] == "PENDING_REVIEW"),
    ({"source": "DEMO"}, lambda i: i["source"] == "DEMO"),
    ({"source": "BACKTEST_REPLAY"}, lambda i: i["source"] == "BACKTEST_REPLAY"),
    ({"min_p_abuse": 0.7}, lambda i: i["p_abuse"] is not None and i["p_abuse"] >= 0.7),
    ({"min_value_inr": 10000}, lambda i: i["order_value"]["inr"] >= 10000),
    ({"graph_evidence": "STRONG"}, lambda i: i["corroborating_signal_count"] >= 1),
    ({"graph_evidence": "NONE"}, lambda i: True),
    ({"graph_evidence": "WEAK_ONLY"}, lambda i: True),
])
def test_queue_filters(shared, params, check):
    c, _ = shared
    q = _queue(c, **params)
    assert all(check(i) for i in q["items"])
    _check_counts(q)


def test_graph_evidence_classes_partition_the_queue(shared):
    c, _ = shared
    total = _queue(c)["total"]
    assert total == SEEDED_DECISIONS + 3
    parts = [_queue(c, graph_evidence=g)["total"] for g in ("STRONG", "WEAK_ONLY", "NONE")]
    assert sum(parts) == total and parts[0] > 0 and parts[2] > 0


@pytest.mark.parametrize("sort,key", [
    ("scored_at_desc", lambda i: i["scored_at"]),
    ("p_abuse_desc", lambda i: i["p_abuse"]),
    ("value_desc", lambda i: i["order_value"]["inr"]),
])
def test_queue_sorts(shared, sort, key):
    c, _ = shared
    values = [key(i) for i in _queue(c, sort=sort)["items"]]
    assert values == sorted(values, reverse=True)


def test_queue_sort_by_exposure(shared):
    c, db = shared
    items = _queue(c, sort="exposure_desc")["items"]
    allow_cost = {}
    for r in _db_rows(db, "SELECT order_id, costs_json FROM decisions"):
        allow_cost[r["order_id"]] = next(x["expected_cost"]["inr"] for x in json.loads(r["costs_json"])
                                         if x["action"] == "ALLOW")
    values = [allow_cost[i["order_id"]] for i in items]
    assert values == sorted(values, reverse=True)


def test_queue_paging_and_unknown_filter(shared):
    c, _ = shared
    page1, page2 = _queue(c, limit=10), _queue(c, limit=10, offset=10)
    assert len(page1["items"]) == 10 and page1["total"] == page2["total"]
    assert not {i["order_id"] for i in page1["items"]} & {i["order_id"] for i in page2["items"]}
    assert c.get(f"{I}/orders", headers=KEY, params={"limit": 201}).status_code == 422
    assert c.get(f"{I}/orders", headers=KEY, params={"bogus": 1}).status_code == 422


# ── audit ────────────────────────────────────────────────────────────────────
def test_audit_events_paging_and_verify(shared):
    c, _ = shared
    res = c.get(f"{I}/audit-events", headers=KEY, params={"limit": 200})
    assert res.status_code == 200 and len(res.json()["items"]) == 200
    assert res.json()["total"] >= SEEDED_DECISIONS + 3
    assert c.get(f"{I}/audit-events", headers=KEY, params={"limit": 201}).status_code == 422
    one = c.get(f"{I}/audit-events", headers=KEY, params={"order_id": "ORD-DEMO-002"}).json()
    assert one["total"] >= 1 and {e["order_id"] for e in one["items"]} == {"ORD-DEMO-002"}
    verify = c.get(f"{I}/audit-events/verify", headers=KEY).json()
    assert verify["valid"] is True and verify["first_broken_seq"] is None


# ── metrics ──────────────────────────────────────────────────────────────────
def test_metrics(shared):
    from sentinel.api.services.runtime import load_evaluation
    c, db = shared
    m = c.get(f"{I}/metrics", headers=KEY).json()
    evaluation = load_evaluation()
    assert m["data_notice"] == DATA_NOTICE
    assert m["drift_monitoring"] == "PLACEHOLDER_NOT_COMPUTED"
    assert m["backtest"] == evaluation["backtest"]
    assert m["models"] == json.loads(json.dumps(evaluation["models"]))
    assert m["cold_start_ring_recall"] == evaluation["cold_start_ring_recall"]
    assert m["sensitivity"] == evaluation["sensitivity"]
    a = m["activity"]
    assert a["version_traceability"] == 1.0 and a["explanation_coverage"] == 1.0
    assert a["orders_evaluated"] == _db_rows(db, "SELECT COUNT(*) AS n FROM decisions")[0]["n"]
    direct = {r["recommended_action"]: r["n"] for r in _db_rows(
        db, "SELECT recommended_action, COUNT(*) AS n FROM decisions GROUP BY recommended_action")}
    assert {k: v for k, v in a["action_distribution"].items() if v} == direct
    assert a["friction_orders"] == direct.get("PREPAID_ONLY", 0) + direct.get("MANUAL_REVIEW", 0)
    assert a["manual_review_volume"] == direct.get("MANUAL_REVIEW", 0)
    avoided = 0.0
    for r in _db_rows(db, "SELECT recommended_action, costs_json FROM decisions WHERE degraded_mode = 0"):
        costs = {x["action"]: x["expected_cost"]["inr"] for x in json.loads(r["costs_json"])}
        avoided += costs["ALLOW"] - costs[r["recommended_action"]]
    assert a["model_estimated_cost_avoided"]["inr"] == pytest.approx(avoided, abs=0.01)


# ── demo endpoints ───────────────────────────────────────────────────────────
def test_demo_endpoints_are_404_when_demo_mode_is_off(seeded_db, data_dir, tmp_path):
    with _client(_copy_db(seeded_db, tmp_path), data_dir, demo_mode=False) as c:
        for method, path in (("GET", "/demo/presets"), ("POST", "/demo/reset")):
            res = c.request(method, f"{I}{path}", headers=KEY)
            assert res.status_code == 404 and res.json() == {"detail": "Not found."}


def test_presets_score_to_their_actions(shared):
    c, _ = shared
    for oid, p in _presets(c).items():
        res = c.post(f"{I}/score-order", json=p, headers=KEY).json()
        assert res["policy"]["selected_action"] == DEMO_ACTIONS[oid]


def test_reset_twice_in_a_row(client):
    client.post(f"{I}/score-order", json=_presets(client)["ORD-DEMO-001"], headers=KEY)
    for _ in range(2):
        res = client.post(f"{I}/demo/reset", headers=KEY)
        assert res.status_code == 200 and res.json() == {"status": "reset", "decisions": SEEDED_DECISIONS}
    assert _queue(client)["total"] == SEEDED_DECISIONS
    # the rebuilt services still score
    assert client.post(f"{I}/score-order", json=_presets(client)["ORD-DEMO-002"], headers=KEY).status_code == 200


# ── money ────────────────────────────────────────────────────────────────────
def _money_fields(value, path="$"):
    if isinstance(value, dict):
        if set(value) == {"inr", "display"}:
            yield path, value
        for k, v in value.items():
            yield from _money_fields(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _money_fields(v, f"{path}[{i}]")


def _money_schema_names(spec) -> int:
    return sum(1 for _ in re.finditer(r'"#/components/schemas/Money"', json.dumps(spec)))


def test_every_money_field_has_a_format_inr_display(shared):
    c, db = shared
    responses = [c.get(f"{I}/orders", headers=KEY, params={"limit": 200}).json(),
                 c.get(f"{I}/metrics", headers=KEY).json(),
                 *[c.get(f"{I}/orders/{oid}", headers=KEY).json() for oid in _detail_orders(db)]]
    seen = 0
    for body in responses:
        for path, money in _money_fields(body):
            seen += 1
            assert isinstance(money["inr"], (int, float)) and money["display"].startswith(("₹", "-₹")), path
            assert money["display"] == format_inr(money["inr"]), path
    assert seen > 400                                  # measured 489 over these responses
    assert _money_schema_names(c.app.openapi()) > 0


# ── latency ──────────────────────────────────────────────────────────────────
def test_score_order_p95_under_300_ms(client):
    presets = list(_presets(client).values())
    client.post(f"{I}/score-order", json=presets[0], headers=KEY)                     # warm-up (not timed)
    timings = []
    for i in range(30):
        p = dict(presets[i % 3], order_id=f"ORD-LAT-{i:03d}")
        start = time.perf_counter()
        res = client.post(f"{I}/score-order", json=p, headers=KEY)
        timings.append((time.perf_counter() - start) * 1000)
        assert res.status_code == 200 and res.json()["idempotent_replay"] is False
    p95 = statistics.quantiles(timings, n=20)[-1]
    print(f"score-order latency over 30 fresh orders: median {statistics.median(timings):.1f} ms, p95 {p95:.1f} ms")
    assert p95 < LATENCY_P95_MS


# ── OpenAPI drift ────────────────────────────────────────────────────────────
def test_committed_openapi_equals_a_fresh_export():
    from sentinel.cli import OPENAPI_PATH, openapi_json
    assert OPENAPI_PATH.read_text(encoding="utf-8") == openapi_json(), \
        "frontend/src/api/openapi.json is stale: run `python -m sentinel.cli export-openapi` then `npm run gen:types`"


# ── policy assumptions (Phase 8 brief 1.2) ───────────────────────────────────
def test_policy_endpoint_returns_the_loaded_config_with_server_formatted_money(shared):
    """Every section and key of policy_v1_0.toml, exactly as the policy engine loaded it, so the UI's
    "Demonstration assumptions" panel never hard-codes a number."""
    from dataclasses import fields

    from sentinel.money import make_money
    from sentinel.policy.config import SECTIONS, load_policy_config

    c, _ = shared
    body = c.get(f"{I}/policy", headers=KEY).json()
    cfg = load_policy_config()
    assert body["policy_version"] == cfg.policy.version
    assert body["policy_config_sha256"] == cfg.config_sha256
    assert body["notice"] == cfg.policy.notice
    assert [s["section"] for s in body["sections"]] == list(SECTIONS)
    checked_money = 0
    for section in body["sections"]:
        loaded = getattr(cfg, section["section"])
        assert [v["key"] for v in section["values"]] == [f.name for f in fields(type(loaded))]
        for value in section["values"]:
            expected = getattr(loaded, value["key"])
            assert value["value"] == expected, (section["section"], value["key"])
            if value["key"].endswith("_inr"):
                assert value["money"] == make_money(expected).model_dump(mode="json")
                checked_money += 1
            else:
                assert value["money"] is None
    assert checked_money >= 8                     # every *_inr key carries a server-formatted Money


def test_policy_endpoint_exposes_the_guardrail_thresholds_the_ui_must_not_invent(shared):
    c, _ = shared
    guardrails = {v["key"]: v["value"] for s in c.get(f"{I}/policy", headers=KEY).json()["sections"]
                  if s["section"] == "guardrails" for v in s["values"]}
    assert set(guardrails) == {"block_min_p_abuse", "block_min_corroborating_signals", "high_exposure_value_inr",
                               "high_exposure_min_p_abuse", "degraded_review_min_value_inr"}
