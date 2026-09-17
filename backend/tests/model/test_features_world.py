"""Phase 3 checkpoint on the generated world: P1, P2, P6 and hard negatives (§7.2, §13.2, §13.3)."""
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from sentinel.api.schemas import ScoreOrderRequest
from sentinel.features.builder import WORLD_TABLES, FeatureBuilder, build_feature_table
from sentinel.features.definitions import FEATURE_SET_VERSION, all_features

pytestmark = pytest.mark.slow


@pytest.fixture(scope="session")
def feature_table(world):
    return build_feature_table(world)


@pytest.fixture(scope="session")
def offline(feature_table):
    return {row["order_id"]: {f: row[f] for f in all_features()}
            for row in feature_table.to_dict("records")}


def _request(world, order_id: str) -> ScoreOrderRequest:
    o = world["orders"].set_index("order_id").loc[order_id]
    lines = world["order_lines"][world["order_lines"]["order_id"] == order_id].sort_values("line_no")
    token = o["payment_token_id"]
    return ScoreOrderRequest(
        order_id=order_id, account_id=o["account_id"], placed_at=o["placed_at"].to_pydatetime(),
        lines=[{"sku_id": r.sku_id, "product_id": r.product_id, "variant": r.variant, "category": r.category,
                "unit_price_inr": float(r.unit_price_inr), "quantity": int(r.quantity)}
               for r in lines.itertuples()],
        discount_pct=float(o["discount_pct"]), delivery_speed=o["delivery_speed"],
        payment_method=o["payment_method"], device_id=o["device_id"], address_id=o["address_id"],
        payment_token_id=None if pd.isna(token) else token)


def _sample(world, n: int, seed: int) -> list[str]:
    ids = world["orders"]["order_id"].sort_values().to_numpy()
    return list(np.random.default_rng(seed).choice(ids, size=n, replace=False))


def _assert_same(a: dict, b: dict) -> None:
    assert a.keys() == b.keys()
    diffs = {k: (a[k], b[k]) for k in a if a[k] != b[k]}
    assert not diffs


# ── table ────────────────────────────────────────────────────────────────────
def test_feature_table_shape(world, feature_table):
    assert len(feature_table) == len(world["orders"])
    assert list(feature_table.columns[:4]) == ["order_id", "split", "t0", "feature_set_version"]
    assert set(feature_table.columns[4:]) == set(all_features())
    assert (feature_table["feature_set_version"] == FEATURE_SET_VERSION).all()
    placed = world["orders"].set_index("order_id")["placed_at"]
    assert (feature_table.set_index("order_id")["t0"] == placed.loc[feature_table["order_id"]]).all()
    assert not feature_table.columns.str.contains("label|archetype|ring").any()


# ── P1: one code path ────────────────────────────────────────────────────────
def test_p1_offline_replay_equals_serving_path(world, offline):
    for order_id in _sample(world, 50, seed=1):
        request = _request(world, order_id)
        builder = FeatureBuilder.replay(world, request.placed_at)
        _assert_same(builder.features_for_request(request), offline[order_id])


# ── P2: rebuild from events strictly before t0 ───────────────────────────────
def _truncated(world, t0) -> dict[str, pd.DataFrame]:
    ts = pd.Timestamp(t0)
    orders = world["orders"][world["orders"]["placed_at"] < ts]
    return {
        "accounts": world["accounts"], "identifiers": world["identifiers"], "orders": orders,
        "order_lines": world["order_lines"][world["order_lines"]["order_id"].isin(orders["order_id"])],
        "order_events": world["order_events"][world["order_events"]["occurred_at"] < ts],
    }


def test_p2_replay_equals_fresh_rebuild(world, offline):
    for order_id in _sample(world, 100, seed=2):
        request = _request(world, order_id)
        fresh = FeatureBuilder.replay(_truncated(world, request.placed_at), request.placed_at)
        _assert_same(fresh.features_for_request(request), offline[order_id])


# ── P6: future poisoning ─────────────────────────────────────────────────────
def _poisoned(world, request: ScoreOrderRequest, rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    t0 = pd.Timestamp(request.placed_at)
    tables = {t: world[t].copy() for t in WORLD_TABLES}
    orders, events, lines = tables["orders"], tables["order_events"], tables["order_lines"]
    earlier = orders[orders["placed_at"] < t0]
    new_events = []
    # confirmations and flags after t0 on earlier orders, including this account's own
    own = earlier[earlier["account_id"] == request.account_id]["order_id"].tolist()
    for oid in own + list(rng.choice(earlier["order_id"], size=min(20, len(earlier)), replace=False)):
        for kind in ("QC_FLAGGED", "ABUSE_CONFIRMED", "RETURN_REQUESTED", "DELIVERED"):
            new_events.append((oid, kind, t0 + pd.Timedelta(seconds=int(rng.integers(0, 30 * 86400)))))
    # new orders on the same device, token and address by other accounts, at or after t0
    others = world["accounts"]["account_id"].sample(5, random_state=int(rng.integers(1_000_000))).tolist()
    new_orders = []
    for i, account in enumerate(others):
        oid = f"ORD-POISON-{i}"
        placed = t0 + pd.Timedelta(seconds=int(rng.integers(0, 3 * 86400)) if i else 0)
        new_orders.append({**orders.iloc[0].to_dict(), "order_id": oid, "account_id": account, "placed_at": placed,
                           "device_id": request.device_id, "address_id": request.address_id,
                           "payment_token_id": request.payment_token_id or orders.iloc[0]["payment_token_id"],
                           "payment_method": request.payment_method if request.payment_token_id else "PREPAID_CARD"})
        lines = pd.concat([lines, pd.DataFrame([{"order_id": oid, "line_no": 1, "sku_id": request.lines[0].sku_id,
                                                 "product_id": "PRD-X", "variant": "M", "category": "APPAREL",
                                                 "unit_price_inr": 999.0, "quantity": 1}])], ignore_index=True)
        new_events.append((oid, "ABUSE_CONFIRMED", placed + pd.Timedelta(hours=1)))
    orders = pd.concat([orders, pd.DataFrame(new_orders).astype(orders.dtypes.to_dict())], ignore_index=True)
    extra = pd.DataFrame(new_events, columns=["order_id", "event_type", "occurred_at"])
    extra["occurred_at"] = extra["occurred_at"].astype(events["occurred_at"].dtype)
    extra["attributes_json"] = "{}"
    extra["event_id"] = np.arange(len(events) + 1, len(events) + 1 + len(extra))
    events = pd.concat([events, extra[events.columns]], ignore_index=True)
    return {**tables, "orders": orders, "order_lines": lines, "order_events": events}


def test_p6_future_poisoning_leaves_features_unchanged(world, offline):
    rng = np.random.default_rng(6)
    for order_id in _sample(world, 15, seed=6):
        request = _request(world, order_id)
        poisoned = _poisoned(world, request, rng)
        builder = FeatureBuilder.replay(poisoned, request.placed_at)
        _assert_same(builder.features_for_request(request), offline[order_id])


# ── hard negatives (§5, §13.3) ───────────────────────────────────────────────
def test_hard_negative_cohorts_do_not_look_like_rings(world, feature_table):
    f = feature_table.merge(world["orders"][["order_id", "account_id"]], on="order_id") \
        .merge(world["sim_ground_truth"], on="account_id")
    normal_size = f.loc[f["archetype"] == "NORMAL", "component_size_reliable_90d"].median()
    for cohort in ("HOUSEHOLD", "OFFICE_HOSTEL_PG", "REFURB_DEVICE"):
        c = f[f["archetype"] == cohort]
        assert c["component_size_reliable_90d"].median() <= normal_size + 2, cohort
        assert c["device_confirmed_abuse_weight"].median() == 0, cohort
