"""Model-level fixtures. The session-scoped `world` fixture lives in tests/conftest.py."""
import pytest


@pytest.fixture(scope="session")
def orders_with_truth(world):
    return (world["orders"]
            .merge(world["sim_ground_truth"], on="account_id")
            .merge(world["order_labels"], on="order_id"))
