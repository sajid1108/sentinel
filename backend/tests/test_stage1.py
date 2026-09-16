"""Stage 1 tests: health endpoint, schema validation, config loading."""
import pytest


class TestHealthEndpoint:
    """Test the health endpoint returns expected response."""

    def test_health_returns_200(self):
        from fastapi.testclient import TestClient
        from sentinel.api.main import app

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_body(self):
        from fastapi.testclient import TestClient
        from sentinel.api.main import app

        client = TestClient(app)
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "sentinel"
        assert "version" in data


class TestPolicyConfig:
    """Test policy configuration loading and validation."""

    def test_load_policy_config(self):
        from sentinel.policy.config import load_policy_config

        cfg = load_policy_config()
        assert cfg.policy.version == "v1.0"
        assert cfg.policy.currency == "INR"

    def test_config_values(self):
        from sentinel.policy.config import load_policy_config

        cfg = load_policy_config()
        assert cfg.economics.gross_margin_rate == 0.30
        assert cfg.economics.reverse_logistics_cost_inr == 150
        assert cfg.allow.abuse_recovery_rate == 0.15
        assert cfg.prepaid_only.abuser_deterrence_rate == 0.30
        assert cfg.prepaid_only.abuse_recovery_rate == 0.50
        assert cfg.manual_review.review_cost_inr == 250
        assert cfg.manual_review.reviewer_detection_rate == 0.80
        assert cfg.block.genuine_clv_churn_rate == 0.60
        assert cfg.guardrails.block_min_p_abuse == 0.70
        assert cfg.guardrails.block_min_corroborating_signals == 2

    def test_config_sha256_is_deterministic(self):
        from sentinel.policy.config import load_policy_config

        cfg1 = load_policy_config()
        cfg2 = load_policy_config()
        assert cfg1.config_sha256 == cfg2.config_sha256
        assert len(cfg1.config_sha256) == 64

    def test_config_validation_passes(self):
        from sentinel.policy.config import load_policy_config, validate_policy_config

        cfg = load_policy_config()
        warnings = validate_policy_config(cfg)
        assert len(warnings) == 0, f"Unexpected validation warnings: {warnings}"


class TestSchemas:
    """Test Pydantic schema validation."""

    def test_action_enum(self):
        from sentinel.api.schemas import Action

        assert Action.ALLOW == "ALLOW"
        assert Action.PREPAID_ONLY == "PREPAID_ONLY"
        assert Action.MANUAL_REVIEW == "MANUAL_REVIEW"
        assert Action.BLOCK == "BLOCK"

    def test_severity_ordering(self):
        from sentinel.api.schemas import Action, SEVERITY

        assert SEVERITY[Action.ALLOW] < SEVERITY[Action.PREPAID_ONLY]
        assert SEVERITY[Action.PREPAID_ONLY] < SEVERITY[Action.MANUAL_REVIEW]
        assert SEVERITY[Action.MANUAL_REVIEW] < SEVERITY[Action.BLOCK]

    def test_hashed_id_validation(self, valid_placed_at):
        from pydantic import ValidationError
        from sentinel.api.schemas import ScoreOrderRequest

        # Valid 32-char hex
        valid_id = "a" * 32

        # Invalid: too short
        with pytest.raises(ValidationError):
            ScoreOrderRequest(
                order_id="ORD-TEST-001",
                account_id="ACC-TEST-001",
                placed_at=valid_placed_at,
                lines=[{
                    "sku_id": "SKU-001",
                    "product_id": "PROD-001",
                    "variant": "M",
                    "category": "APPAREL",
                    "unit_price_inr": 1000,
                    "quantity": 1,
                }],
                discount_pct=0,
                delivery_speed="STANDARD",
                payment_method="PREPAID_UPI",
                device_id="short",  # invalid
                address_id=valid_id,
                payment_token_id=valid_id,
            )

    def test_cod_requires_no_token(self, valid_placed_at):
        from pydantic import ValidationError
        from sentinel.api.schemas import ScoreOrderRequest

        valid_id = "a" * 32

        # COD with a token should fail
        with pytest.raises(ValidationError):
            ScoreOrderRequest(
                order_id="ORD-TEST-002",
                account_id="ACC-TEST-002",
                placed_at=valid_placed_at,
                lines=[{
                    "sku_id": "SKU-001",
                    "product_id": "PROD-001",
                    "variant": "M",
                    "category": "APPAREL",
                    "unit_price_inr": 1000,
                    "quantity": 1,
                }],
                discount_pct=0,
                delivery_speed="STANDARD",
                payment_method="COD",
                device_id=valid_id,
                address_id=valid_id,
                payment_token_id=valid_id,  # should be None for COD
            )

    def test_prepaid_requires_token(self, valid_placed_at):
        from pydantic import ValidationError
        from sentinel.api.schemas import ScoreOrderRequest

        valid_id = "a" * 32

        # Prepaid without a token should fail
        with pytest.raises(ValidationError):
            ScoreOrderRequest(
                order_id="ORD-TEST-003",
                account_id="ACC-TEST-003",
                placed_at=valid_placed_at,
                lines=[{
                    "sku_id": "SKU-001",
                    "product_id": "PROD-001",
                    "variant": "M",
                    "category": "APPAREL",
                    "unit_price_inr": 1000,
                    "quantity": 1,
                }],
                discount_pct=0,
                delivery_speed="STANDARD",
                payment_method="PREPAID_UPI",
                device_id=valid_id,
                address_id=valid_id,
                payment_token_id=None,  # should be present for prepaid
            )

    def test_money_format(self):
        from sentinel.money import format_inr

        assert format_inr(1490) == "₹1,490"
        assert format_inr(100000) == "₹1,00,000"
        assert format_inr(500) == "₹500"

    def test_extra_fields_forbidden(self):
        from pydantic import ValidationError
        from sentinel.api.schemas import Money

        with pytest.raises(ValidationError):
            Money(inr=100, display="₹100", extra_field="bad")

    def test_checkout_outcome_no_scores(self):
        """Verify the checkout response contract has no score fields."""
        from sentinel.api.schemas import CheckoutOutcome

        fields = set(CheckoutOutcome.model_fields.keys())
        assert "p_return" not in fields
        assert "p_abuse" not in fields
        assert "reasons" not in fields
        assert "costs" not in fields
        # Only allowed fields
        assert fields == {"order_id", "outcome", "customer_message", "support_reference"}


class TestSettings:
    """Test settings module."""

    def test_demo_clock_is_fixed(self):
        from sentinel.settings import DEMO_CLOCK
        from datetime import datetime, timezone, timedelta

        IST = timezone(timedelta(hours=5, minutes=30))
        expected = datetime(2026, 9, 1, 10, 30, 0, tzinfo=IST)
        assert DEMO_CLOCK == expected

    def test_demo_clock_is_timezone_aware(self):
        from sentinel.settings import DEMO_CLOCK

        assert DEMO_CLOCK.tzinfo is not None

    def test_paths_exist(self):
        from sentinel.settings import CONFIG_DIR

        assert CONFIG_DIR.exists()


class TestDatabaseSchema:
    """Test that the database schema can be loaded."""

    def test_schema_file_exists(self):
        from pathlib import Path
        schema_path = Path(__file__).resolve().parent.parent / "sentinel" / "db" / "schema.sql"
        assert schema_path.exists(), f"schema.sql not found at {schema_path}"

    def test_schema_creates_tables(self):
        """Test that the schema can create a database in memory."""
        import sqlite3
        from pathlib import Path

        schema_path = Path(__file__).resolve().parent.parent / "sentinel" / "db" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")

        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)

        # Check tables exist
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "accounts", "identifiers", "orders", "order_lines", "order_events",
            "order_labels", "sim_ground_truth", "policy_versions", "model_registry",
            "decisions", "audit_events", "probe_events",
        }
        assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"

        conn.close()

    def test_audit_triggers_exist(self):
        """Test that append-only triggers are created."""
        import sqlite3
        from pathlib import Path

        schema_path = Path(__file__).resolve().parent.parent / "sentinel" / "db" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")

        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")
        triggers = {row[0] for row in cursor.fetchall()}

        assert "audit_no_update" in triggers
        assert "audit_no_delete" in triggers
        assert "decisions_core_immutable" in triggers

        conn.close()
