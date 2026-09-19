"""Phase 10 §A and §D: GET /internal/demo/order-builder and the "Try an order" checkout path.

Uses the Phase 7 fixtures (a world generated in-process, seeded into a temporary database). Auth and the
DEMO_MODE-off 404 for this route are in test_api.py's route tables with every other internal route.
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from sentinel.api.services import order_builder
from sentinel.db.models import utc_iso
from tests.api.test_api import (CHECKOUT, DEMO_ACTIONS, KEY, I, _client, _copy_db, _db_rows,  # noqa: F401
                                data_dir, seeded_db)

pytestmark = pytest.mark.slow

HEX32 = re.compile(r"^[a-f0-9]{32}$")
BUILDER = f"{I}/demo/order-builder"
CATEGORIES = ["APPAREL", "FOOTWEAR", "ELECTRONICS", "BEAUTY", "HOME", "ACCESSORIES"]


@pytest.fixture(scope="module")
def app(seeded_db, data_dir, tmp_path_factory):
    db = _copy_db(seeded_db, tmp_path_factory.mktemp("try-order"))
    with _client(db, data_dir) as c:
        yield c, db


def _builder(c) -> dict:
    res = c.get(BUILDER, headers=KEY)
    assert res.status_code == 200, res.text
    return res.json()


def _presets(c) -> list[dict]:
    return c.get(f"{I}/demo/presets", headers=KEY).json()


# ── §A the builder route ─────────────────────────────────────────────────────
def test_builder_offers_the_presets_placed_at_their_accounts_and_the_six_categories(app):
    c, _ = app
    body, presets = _builder(c), _presets(c)
    assert {p["placed_at"] for p in presets} == {body["placed_at"]}
    ids = [a["account_id"] for a in body["accounts"]]
    assert ids[:len(presets)] == [p["account_id"] for p in presets]
    assert len(ids) == len(set(ids))
    assert body["categories"] == CATEGORIES
    assert [o["option"] for o in body["devices"]][:2] == ["OWN", "NEW"]
    assert [o["option"] for o in body["tokens"]][:2] == ["OWN", "NEW"]


def test_builder_accounts_are_data_derived(app):
    c, db = app
    body, presets = _builder(c), _presets(c)
    rest = body["accounts"][len(presets):]
    discounted = [a for a in rest if a["label"] in order_builder.DISCOUNT_LABELS.values()]
    new = [a for a in rest if a["label"] == order_builder.NEW_ACCOUNT_LABEL]
    assert discounted + new == rest
    assert 0 < len(discounted) <= order_builder.MAX_DISCOUNTED_ACCOUNTS
    assert len(new) <= order_builder.MAX_NEW_ACCOUNTS
    for a in discounted:           # the label is the reason on one of the account's own stored decisions
        reasons = {link["reason"] for r in _db_rows(
            db, "SELECT d.discounted_links_json FROM decisions d JOIN orders o USING (order_id) "
                "WHERE o.account_id = ?", a["account_id"]) for link in json.loads(r["discounted_links_json"])}
        assert order_builder.DISCOUNT_LABELS.keys() & reasons
    t0 = utc_iso(datetime.fromisoformat(body["placed_at"]))
    for a in body["accounts"]:     # own identifiers are the account's latest before placed_at
        rows = _db_rows(db, "SELECT device_id, address_id, payment_token_id FROM orders WHERE account_id = ? "
                            "AND source = 'HISTORY' AND placed_at < ? ORDER BY placed_at DESC, order_id DESC",
                        a["account_id"], t0)
        assert a["prior_orders"] == len(rows) and a["account_age_days"] >= 0
        if rows:
            assert (a["device_id"], a["address_id"]) == (rows[0]["device_id"], rows[0]["address_id"])
            assert a["payment_token_id"] == next((r["payment_token_id"] for r in rows if r["payment_token_id"]), None)
        else:
            assert a["device_id"] is None and a["payment_token_id"] is None


def test_every_identifier_is_a_32_hex_hash(app):
    c, _ = app
    body = _builder(c)
    ids = [a[k] for a in body["accounts"] for k in ("device_id", "address_id", "payment_token_id")]
    ids += [o["identifier_id"] for o in body["devices"] + body["tokens"]]
    assert all(i is None or HEX32.match(i) for i in ids)
    assert all(a["address_id"] is not None for a in body["accounts"])
    for options in (body["devices"], body["tokens"]):
        own = [o for o in options if o["option"] == "OWN"]
        assert [o["identifier_id"] for o in own] == [None]
        assert all(o["identifier_id"] is not None for o in options if o["option"] != "OWN")


def test_new_identifiers_are_fresh_on_every_request(app):
    c, _ = app
    first, second = _builder(c), _builder(c)
    for kind in ("devices", "tokens"):
        new = [next(o["identifier_id"] for o in b[kind] if o["option"] == "NEW") for b in (first, second)]
        assert new[0] != new[1]


def test_ring_options_are_the_presets_with_the_strongest_recorded_evidence(app):
    c, db = app
    body = _builder(c)                                   # before any preset is scored
    for p in _presets(c):
        assert c.post(f"{I}/demo/presets/{p['order_id']}/score", headers=KEY).status_code == 200
    presets = {p["order_id"]: p for p in _presets(c)}
    recorded = {}
    for oid in presets:
        row = _db_rows(db, "SELECT features_json, graph_summary_json FROM decisions WHERE order_id = ?", oid)[0]
        features, summary = json.loads(row["features_json"]), json.loads(row["graph_summary_json"])
        token = next(s for s in summary["signals"] if s["signal"] == "PAYMENT_TOKEN")
        recorded[oid] = (features["device_confirmed_abuse_weight"], token["weight"],
                         features["token_other_accounts_30d"])
    device_oid = max(presets, key=lambda o: recorded[o][0])
    token_oid = max((o for o in presets if presets[o]["payment_token_id"]), key=lambda o: recorded[o][1:])
    assert recorded[device_oid][0] > 0
    ring = {kind: next(o["identifier_id"] for o in body[kind] if o["option"] == "RING") for kind in ("devices", "tokens")}
    assert ring["devices"] == presets[device_oid]["device_id"]
    assert ring["tokens"] == presets[token_oid]["payment_token_id"]
    assert _builder(c)["devices"][-1]["identifier_id"] == ring["devices"]      # unchanged once recorded


def test_builder_imports_no_generator_or_ground_truth_module():
    code = ("import sys, sentinel.api.services.order_builder, sentinel.api.routers.demo; "
            "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('sentinel.'))))")
    loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                            cwd=Path(__file__).resolve().parents[2]).stdout.split()
    forbidden = ("sentinel.data.generator", "sentinel.data.archetypes", "sentinel.data.labels", "sentinel.evaluation")
    assert "sentinel.api.services.order_builder" in loaded
    assert not [m for m in loaded if m.startswith(forbidden)]


# ── §D scenario: the Part C orders ───────────────────────────────────────────
def _part_c_orders(body: dict, preset: dict) -> list[dict]:
    """Demo 1's cart with its account's own device and token, then the ring's device, then device and card."""
    account = next(a for a in body["accounts"] if a["account_id"] == preset["account_id"])
    ring = {k: next(o["identifier_id"] for o in body[k] if o["option"] == "RING") for k in ("devices", "tokens")}
    base = dict(preset, placed_at=body["placed_at"], device_id=account["device_id"],
                address_id=account["address_id"], payment_token_id=account["payment_token_id"])
    return [dict(base, order_id="ORD-TRY-C0000001"),
            dict(base, order_id="ORD-TRY-C0000002", device_id=ring["devices"]),
            dict(base, order_id="ORD-TRY-C0000003", device_id=ring["devices"], payment_token_id=ring["tokens"])]


def test_part_c_orders_score_and_each_writes_a_verified_audit_event(seeded_db, data_dir, tmp_path):
    with _client(_copy_db(seeded_db, tmp_path), data_dir) as c:
        body = _builder(c)
        preset = next(p for p in _presets(c) if p["order_id"] == "ORD-DEMO-001")
        for order in _part_c_orders(body, preset):
            res = c.post(CHECKOUT, json=order)
            assert res.status_code == 200, res.text
            assert set(res.json()) == {"order_id", "outcome", "customer_message", "support_reference"}
            detail = c.get(f"{I}/orders/{order['order_id']}", headers=KEY).json()
            assert detail["decision"]["degraded_mode"] is False
            assert detail["decision"]["idempotent_replay"] is False
            events = [e for e in detail["audit_events"] if e["event_type"] == "DECISION_CREATED"]
            assert len(events) == 1 and events[0]["event_id"] == detail["decision"]["audit_event_id"]
            src = _db_rows(c.app.state.services.db_path, "SELECT source FROM decisions WHERE order_id = ?",
                           order["order_id"])
            assert src == [{"source": "LIVE"}]
        verify = c.get(f"{I}/audit-events/verify", headers=KEY).json()
        assert verify["valid"] is True and verify["first_broken_seq"] is None
