"""One synthetic world per test session; generation is deterministic (§5)."""
import pytest

from sentinel.data.generator import generate


@pytest.fixture(scope="session")
def world():
    return generate()


@pytest.fixture(scope="session")
def orders_with_truth(world):
    return (world["orders"]
            .merge(world["sim_ground_truth"], on="account_id")
            .merge(world["order_labels"], on="order_id"))
