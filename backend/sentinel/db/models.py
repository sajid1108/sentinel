"""SQLAlchemy 2.0 ORM models for Sentinel.

Tables are created only by ``create_database()``; never call
``Base.metadata.create_all()`` — it would skip the triggers and
CHECK constraints defined in schema.sql.
"""

import pathlib
import sqlite3
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


ACTIONS_SQL = "('ALLOW','PREPAID_ONLY','MANUAL_REVIEW','BLOCK')"
SELECTED_RULES_SQL = "('MIN_EXPECTED_COST','MIN_EXPECTED_COST_WITHIN_GUARDRAILS','DEGRADED_MODE_FALLBACK')"


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (CheckConstraint("source IN ('SYNTHETIC','DEMO')"),)


class Identifier(Base):
    __tablename__ = "identifiers"

    identifier_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    is_multi_tenant: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    multi_tenant_set_at: Mapped[Optional[str]] = mapped_column(String)
    display_label: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("length(identifier_id) = 32"),
        CheckConstraint("kind IN ('DEVICE','ADDRESS','PAYMENT_TOKEN')"),
    )


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    placed_at: Mapped[str] = mapped_column(String, nullable=False)
    order_value_inr: Mapped[float] = mapped_column(Float, nullable=False)
    discount_pct: Mapped[float] = mapped_column(Float, nullable=False)
    n_items: Mapped[int] = mapped_column(Integer, nullable=False)
    n_variants_same_product: Mapped[int] = mapped_column(Integer, nullable=False)
    primary_category: Mapped[str] = mapped_column(String, nullable=False)
    delivery_speed: Mapped[str] = mapped_column(String, nullable=False)
    payment_method: Mapped[str] = mapped_column(String, nullable=False)
    device_id: Mapped[str] = mapped_column(ForeignKey("identifiers.identifier_id"), nullable=False)
    address_id: Mapped[str] = mapped_column(ForeignKey("identifiers.identifier_id"), nullable=False)
    payment_token_id: Mapped[Optional[str]] = mapped_column(ForeignKey("identifiers.identifier_id"))
    source: Mapped[str] = mapped_column(String, nullable=False)
    split: Mapped[Optional[str]] = mapped_column(String)

    __table_args__ = (
        CheckConstraint("order_value_inr > 0"),
        CheckConstraint("discount_pct BETWEEN 0 AND 90"),
        CheckConstraint("n_items >= 1"),
        CheckConstraint("delivery_speed IN ('STANDARD','EXPRESS')"),
        CheckConstraint("payment_method IN ('PREPAID_CARD','PREPAID_UPI','COD')"),
        CheckConstraint("source IN ('HISTORY','DEMO','LIVE')"),
        CheckConstraint("split IN ('TRAIN','GAP','CALIBRATION','TEST','RECENT')"),
        CheckConstraint("(payment_method = 'COD') = (payment_token_id IS NULL)"),
        Index("ix_orders_account_time", "account_id", "placed_at"),
        Index("ix_orders_device_time", "device_id", "placed_at"),
        Index("ix_orders_token_time", "payment_token_id", "placed_at"),
        Index("ix_orders_address_time", "address_id", "placed_at"),
    )


class OrderLine(Base):
    __tablename__ = "order_lines"

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku_id: Mapped[str] = mapped_column(String, nullable=False)
    product_id: Mapped[str] = mapped_column(String, nullable=False)
    variant: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    unit_price_inr: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class OrderEvent(Base):
    __tablename__ = "order_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
    attributes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'DELIVERED','RTO','CANCELLED',"
            "'RETURN_REQUESTED','EXCHANGE_REQUESTED','CLAIM_FILED',"
            "'QC_PASSED','QC_FLAGGED','CARRIER_EVIDENCE',"
            "'ABUSE_CONFIRMED','ABUSE_CLEARED','REFUNDED')"
        ),
        Index("ix_order_events_order_time", "order_id", "occurred_at"),
        Index("ix_order_events_type_time", "event_type", "occurred_at"),
    )


class OrderLabel(Base):
    __tablename__ = "order_labels"

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), primary_key=True)
    return_label: Mapped[Optional[int]] = mapped_column(Integer)
    return_type: Mapped[Optional[str]] = mapped_column(String)
    returned_value_fraction: Mapped[Optional[float]] = mapped_column(Float)
    abuse_status: Mapped[str] = mapped_column(String, nullable=False)
    abuse_label: Mapped[Optional[int]] = mapped_column(Integer)
    return_label_resolved_at: Mapped[Optional[str]] = mapped_column(String)
    abuse_label_resolved_at: Mapped[Optional[str]] = mapped_column(String)
    label_definition_version: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("return_type IN ('NONE','FULL','PARTIAL','EXCHANGE')"),
        CheckConstraint(
            "abuse_status IN ('CONFIRMED','CLEARED','NO_CLAIM','UNRESOLVED','NOT_MATURED')"
        ),
    )


class SimGroundTruth(Base):
    __tablename__ = "sim_ground_truth"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    archetype: Mapped[str] = mapped_column(String, nullable=False)
    ring_id: Mapped[Optional[str]] = mapped_column(String)


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    policy_version: Mapped[str] = mapped_column(String, primary_key=True)
    config_toml: Mapped[str] = mapped_column(Text, nullable=False)
    config_sha256: Mapped[str] = mapped_column(String, nullable=False)
    activated_at: Mapped[str] = mapped_column(String, nullable=False)


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    model_version: Mapped[str] = mapped_column(String, primary_key=True)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    trained_at: Mapped[str] = mapped_column(String, nullable=False)
    train_window: Mapped[str] = mapped_column(String, nullable=False)
    calibration_window: Mapped[str] = mapped_column(String, nullable=False)
    calibration_method: Mapped[str] = mapped_column(String, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String, nullable=False)
    features_json: Mapped[str] = mapped_column(Text, nullable=False)
    sklearn_version: Mapped[str] = mapped_column(String, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("model_name IN ('RETURN','ABUSE')"),
        CheckConstraint("calibration_method IN ('ISOTONIC','SIGMOID')"),
    )


class Decision(Base):
    __tablename__ = "decisions"

    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), unique=True, nullable=False)
    scored_at: Mapped[str] = mapped_column(String, nullable=False)
    features_as_of: Mapped[str] = mapped_column(String, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String, nullable=False)
    features_json: Mapped[str] = mapped_column(Text, nullable=False)
    p_return: Mapped[Optional[float]] = mapped_column(Float)          # NULL only when degraded
    p_abuse: Mapped[Optional[float]] = mapped_column(Float)
    p_abuse_without_graph: Mapped[Optional[float]] = mapped_column(Float)
    return_model_version: Mapped[str] = mapped_column(ForeignKey("model_registry.model_version"), nullable=False)
    abuse_model_version: Mapped[str] = mapped_column(ForeignKey("model_registry.model_version"), nullable=False)
    policy_version: Mapped[str] = mapped_column(ForeignKey("policy_versions.policy_version"), nullable=False)
    cost_optimal_action: Mapped[Optional[str]] = mapped_column(String)  # NULL only when degraded
    recommended_action: Mapped[str] = mapped_column(String, nullable=False)
    current_action: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    selected_rule: Mapped[str] = mapped_column(String, nullable=False)
    costs_json: Mapped[str] = mapped_column(Text, nullable=False)
    guardrails_json: Mapped[str] = mapped_column(Text, nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    graph_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    degraded_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String, nullable=False)
    latest_audit_event_id: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("p_return IS NULL OR p_return BETWEEN 0 AND 1"),
        CheckConstraint("p_abuse IS NULL OR p_abuse BETWEEN 0 AND 1"),
        CheckConstraint("(degraded_mode = 1) OR "
                        "(p_return IS NOT NULL AND p_abuse IS NOT NULL AND cost_optimal_action IS NOT NULL)"),
        CheckConstraint("status IN ('AUTO_APPLIED','PENDING_REVIEW','OVERRIDDEN','APPEAL_OPEN')"),
        CheckConstraint("source IN ('DEMO','BACKTEST_REPLAY','LIVE')"),
        CheckConstraint(f"cost_optimal_action IS NULL OR cost_optimal_action IN {ACTIONS_SQL}"),
        CheckConstraint(f"recommended_action IN {ACTIONS_SQL}"),
        CheckConstraint(f"current_action IN {ACTIONS_SQL}"),
        CheckConstraint(f"selected_rule IN {SELECTED_RULES_SQL}"),
        Index("ix_decisions_queue", "status", "current_action", "scored_at"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), nullable=False)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.decision_id"), nullable=False)
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    previous_action: Mapped[Optional[str]] = mapped_column(String)
    new_action: Mapped[str] = mapped_column(String, nullable=False)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    return_model_version: Mapped[str] = mapped_column(String, nullable=False)
    abuse_model_version: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    event_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    __table_args__ = (
        CheckConstraint("event_type IN ('DECISION_CREATED','OVERRIDE_APPLIED','APPEAL_OPENED')"),
        CheckConstraint("actor_type IN ('SYSTEM','REVIEWER')"),
        CheckConstraint(f"previous_action IS NULL OR previous_action IN {ACTIONS_SQL}"),
        CheckConstraint(f"new_action IN {ACTIONS_SQL}"),
        Index("ix_audit_order", "order_id", "seq"),
    )


class ProbeEvent(Base):
    __tablename__ = "probe_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
    device_id: Mapped[Optional[str]] = mapped_column(String)
    account_id: Mapped[Optional[str]] = mapped_column(String)
    attempts_24h: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_carts_24h: Mapped[int] = mapped_column(Integer, nullable=False)


def create_database(db_path: str | pathlib.Path) -> None:
    """Create the database from the raw SQL schema."""
    db_path_obj = pathlib.Path(db_path)
    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = (pathlib.Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path_obj)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


def delete_database(db_path: str | pathlib.Path, engine=None) -> None:
    """Delete the database file and WAL/SHM companions. Disposes engine first."""
    if engine is not None:
        engine.dispose()
    base = pathlib.Path(db_path)
    for p in (base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")):
        p.unlink(missing_ok=True)


def get_engine(db_path: str | pathlib.Path):
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def get_session_factory(engine):
    return sessionmaker(bind=engine)
