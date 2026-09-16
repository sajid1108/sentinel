"""Shared fixtures. Tests never read the wall clock: time is anchored to DEMO_CLOCK."""
from datetime import timedelta

import pytest

from sentinel.settings import DEMO_CLOCK

VALID_ID = "a" * 32


@pytest.fixture
def valid_placed_at():
    """Demo orders are placed at DEMO_CLOCK - 5 min (§11)."""
    return DEMO_CLOCK - timedelta(minutes=5)


@pytest.fixture
def order_payload(valid_placed_at):
    """A valid ScoreOrderRequest payload; tests override fields as needed."""
    return {
        "order_id": "ORD-TEST-001",
        "account_id": "ACC-TEST-001",
        "placed_at": valid_placed_at,
        "lines": [{
            "sku_id": "SKU-001",
            "product_id": "PROD-001",
            "variant": "M",
            "category": "APPAREL",
            "unit_price_inr": 1000,
            "quantity": 1,
        }],
        "discount_pct": 0,
        "delivery_speed": "STANDARD",
        "payment_method": "PREPAID_UPI",
        "device_id": VALID_ID,
        "address_id": VALID_ID,
        "payment_token_id": VALID_ID,
    }
