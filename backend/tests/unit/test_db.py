"""Schema integrity on a real temp-file database: triggers, CHECKs, foreign keys, cleanup."""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import sentinel.db.models as models
from sentinel.db.models import create_database, delete_database, get_engine

SCHEMA_SQL = (Path(models.__file__).parent / "schema.sql").read_text(encoding="utf-8")
MUTABLE_DECISION_COLUMNS = {"current_action", "status", "latest_audit_event_id"}
ID_A, ID_B = "a" * 32, "b" * 32
GENESIS = "0" * 64

SEED_SQL = f"""
INSERT INTO accounts VALUES ('ACC-T-1', '2026-01-01T00:00:00Z', 'DEMO');
INSERT INTO identifiers VALUES ('{ID_A}', 'DEVICE', 0, NULL, 'Device aaaa');
INSERT INTO identifiers VALUES ('{ID_B}', 'ADDRESS', 0, NULL, 'Address bbbb');
INSERT INTO orders VALUES ('ORD-T-1', 'ACC-T-1', '2026-09-01T04:55:00Z', 4500, 10, 3, 3,
    'APPAREL', 'STANDARD', 'COD', '{ID_A}', '{ID_B}', NULL, 'DEMO', NULL);
INSERT INTO policy_versions VALUES ('v1.0', 'toml', 'sha', '2026-09-01T00:00:00Z');
INSERT INTO model_registry VALUES ('ret-1', 'RETURN', 't', 'w', 'c', 'ISOTONIC', 'fs-1.0', '[]', '1', 's', '{{}}');
INSERT INTO model_registry VALUES ('abu-1', 'ABUSE', 't', 'w', 'c', 'SIGMOID', 'fs-1.0', '[]', '1', 's', '{{}}');
INSERT INTO decisions VALUES ('DEC-1', 'ORD-T-1', '2026-09-01T05:00:00Z', '2026-09-01T04:55:00Z',
    'fs-1.0', '{{}}', 0.75, 0.03, NULL, 'ret-1', 'abu-1', 'v1.0', 'ALLOW', 'ALLOW', 'ALLOW',
    'AUTO_APPLIED', 'MIN_EXPECTED_COST', '[]', '[]', '[]', '{{}}', 0, 'DEMO', 'EVT-1');
INSERT INTO audit_events (event_id, event_type, occurred_at, order_id, decision_id, actor_type,
    actor_id, previous_action, new_action, policy_version, return_model_version,
    abuse_model_version, payload_json, prev_hash, event_hash)
VALUES ('EVT-1', 'DECISION_CREATED', '2026-09-01T05:00:00Z', 'ORD-T-1', 'DEC-1', 'SYSTEM',
    'sentinel-scoring', NULL, 'ALLOW', 'v1.0', 'ret-1', 'abu-1', '{{}}', '{GENESIS}', 'h1');
"""


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "sentinel.db"
    create_database(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SEED_SQL)
    conn.commit()
    yield conn
    conn.close()
    delete_database(path)


def _decision_columns() -> list[str]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA_SQL)
        return [row[1] for row in conn.execute("PRAGMA table_info(decisions)")]
    finally:
        conn.close()


PROTECTED = [c for c in _decision_columns() if c not in MUTABLE_DECISION_COLUMNS]


def test_audit_events_update_aborts(db):
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("UPDATE audit_events SET actor_id = 'x'")


def test_audit_events_delete_aborts(db):
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("DELETE FROM audit_events")


def test_protected_column_list_is_complete():
    assert len(_decision_columns()) == 24
    assert len(PROTECTED) == 21


@pytest.mark.parametrize("column", PROTECTED)
def test_protected_decision_column_update_aborts(db, column):
    # UPDATE OF triggers fire whenever the column is in the SET list, even if the value is unchanged.
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        db.execute(f"UPDATE decisions SET {column} = {column}")


@pytest.mark.parametrize("column, value", [
    ("current_action", "BLOCK"),
    ("status", "OVERRIDDEN"),
    ("latest_audit_event_id", "EVT-2"),
])
def test_mutable_decision_columns_update(db, column, value):
    db.execute(f"UPDATE decisions SET {column} = ?", (value,))
    db.commit()
    assert db.execute(f"SELECT {column} FROM decisions").fetchone()[0] == value


def test_current_action_typo_rejected(db):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute("UPDATE decisions SET current_action = 'BLOK'")


@pytest.mark.parametrize("previous, new", [("ALLOW", "BLOK"), ("ALOW", "BLOCK")])
def test_audit_action_checks(db, previous, new):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute(
            """INSERT INTO audit_events (event_id, event_type, occurred_at, order_id, decision_id,
            actor_type, actor_id, previous_action, new_action, policy_version, return_model_version,
            abuse_model_version, payload_json, prev_hash, event_hash)
            VALUES ('EVT-2', 'OVERRIDE_APPLIED', 't', 'ORD-T-1', 'DEC-1', 'REVIEWER', 'r',
            ?, ?, 'v1.0', 'ret-1', 'abu-1', '{}', 'h1', 'h2')""", (previous, new))


def test_selected_rule_check(tmp_path):
    path = tmp_path / "rule.db"
    create_database(path)
    conn = sqlite3.connect(path)
    try:
        bad = SEED_SQL.replace("'MIN_EXPECTED_COST'", "'CHEAPEST'")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.executescript(bad)
    finally:
        conn.close()
        delete_database(path)


DEGRADED_ORDER_SQL = f"""
INSERT INTO orders VALUES ('ORD-T-2', 'ACC-T-1', '2026-09-01T04:56:00Z', 6000, 0, 1, 1,
    'HOME', 'STANDARD', 'COD', '{ID_A}', '{ID_B}', NULL, 'DEMO', NULL);
"""


def _decision_row(degraded_mode: int) -> str:
    return f"""INSERT INTO decisions VALUES ('DEC-2', 'ORD-T-2', '2026-09-01T05:00:00Z', '2026-09-01T04:56:00Z',
        'fs-1.0', '{{}}', NULL, NULL, NULL, 'ret-1', 'abu-1', 'v1.0', NULL, 'MANUAL_REVIEW', 'MANUAL_REVIEW',
        'PENDING_REVIEW', 'DEGRADED_MODE_FALLBACK', '[]', '[]', '[]', '{{}}', {degraded_mode}, 'DEMO', 'EVT-2')"""


def test_non_degraded_decision_without_scores_rejected(db):
    db.executescript(DEGRADED_ORDER_SQL)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute(_decision_row(degraded_mode=0))


def test_degraded_decision_without_scores_accepted(db):
    db.executescript(DEGRADED_ORDER_SQL)
    db.execute(_decision_row(degraded_mode=1))
    db.commit()
    row = db.execute("SELECT p_return, p_abuse, cost_optimal_action FROM decisions WHERE decision_id='DEC-2'").fetchone()
    assert row == (None, None, None)


def test_engine_enables_foreign_keys(tmp_path):
    path = tmp_path / "fk.db"
    create_database(path)
    engine = get_engine(path)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO orders VALUES ('ORD-X', 'ACC-MISSING', 't', 1, 0, 1, 1, 'HOME', "
                    f"'STANDARD', 'COD', '{ID_A}', '{ID_B}', NULL, 'LIVE', NULL)"))
    finally:
        delete_database(path, engine)


def test_create_then_delete_leaves_no_files(tmp_path):
    path = tmp_path / "gone.db"
    create_database(path)
    engine = get_engine(path)
    with engine.connect() as conn:
        conn.execute(text("SELECT count(*) FROM accounts")).scalar()
    delete_database(path, engine)
    assert list(tmp_path.iterdir()) == []


def test_orm_models_declare_action_checks():
    from sentinel.db.models import AuditEvent, Decision

    def checks(table):
        return " ".join(str(c.sqltext) for c in table.constraints if hasattr(c, "sqltext"))

    decision_checks = checks(Decision.__table__)
    for col in ("cost_optimal_action", "recommended_action", "current_action", "selected_rule"):
        assert f"{col} IN" in decision_checks
    audit_checks = checks(AuditEvent.__table__)
    assert "previous_action IS NULL OR previous_action IN" in audit_checks
    assert "new_action IN" in audit_checks
