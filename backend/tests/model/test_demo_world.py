"""§11 demo accounts: hand-authored histories and the raw facts each scenario relies on.

These check events and identifiers, not model features (features are Phase 3).
"""
from datetime import timedelta

import pandas as pd
import pytest

from sentinel.api.schemas import ScoreOrderRequest
from sentinel.data import archetypes as A
from sentinel.data import demo_orders as D
from sentinel.features.identifiers import identifier_id
from sentinel.settings import DEMO_CLOCK

pytestmark = pytest.mark.slow

T0 = pd.Timestamp(D.DEMO_PLACED_AT)


def _visible_orders(world):
    return world["orders"][world["orders"]["placed_at"] < T0]


def _confirmed_accounts(world, before=T0):
    ev = world["order_events"]
    conf = ev[(ev["event_type"] == "ABUSE_CONFIRMED") & (ev["occurred_at"] < before)]
    return conf.merge(world["orders"][["order_id", "account_id"]], on="order_id")


def _others_on(world, column, ident, account, since):
    o = _visible_orders(world)
    hit = o[(o[column] == ident) & (o["account_id"] != account) & (o["placed_at"] >= since)]
    return set(hit["account_id"])


@pytest.fixture(scope="module")
def requests():
    return {r["order_id"]: r for r in D.demo_requests()}


def test_requests_validate_and_are_placed_five_minutes_before_demo_clock(requests):
    assert set(requests) == {"ORD-DEMO-001", "ORD-DEMO-002", "ORD-DEMO-003"}
    for payload in requests.values():
        req = ScoreOrderRequest.model_validate(payload)
        assert req.placed_at == DEMO_CLOCK - timedelta(minutes=5)


def test_demo_accounts_have_fixed_ids_and_demo_source(world):
    acc = world["accounts"].set_index("account_id")
    for account in (D.DEMO_1, D.DEMO_2, D.DEMO_3):
        assert acc.loc[account, "source"] == "DEMO"


def test_demo_orders_are_not_in_the_generated_history(world):
    assert not world["orders"]["order_id"].isin(["ORD-DEMO-001", "ORD-DEMO-002", "ORD-DEMO-003"]).any()


def test_demo_request_identifiers_exist(world, requests):
    idents = set(world["identifiers"]["identifier_id"])
    for r in requests.values():
        assert {r["device_id"], r["address_id"]} <= idents
        assert r["payment_token_id"] is None or r["payment_token_id"] in idents


def _age_days(world, account):
    created = world["accounts"].set_index("account_id").loc[account, "created_at"]
    return (T0 - created) / pd.Timedelta(days=1)


# ── Demo 1 ───────────────────────────────────────────────────────────────────
def test_demo_1_history(world, requests):
    r = requests["ORD-DEMO-001"]
    o = _visible_orders(world)
    mine = o[o["account_id"] == D.DEMO_1]
    assert round(_age_days(world, D.DEMO_1)) == 1280
    assert len(mine) == 52
    ev = world["order_events"][world["order_events"]["order_id"].isin(mine["order_id"])]
    assert not ev["event_type"].isin(["CLAIM_FILED", "QC_FLAGGED", "ABUSE_CONFIRMED"]).any()
    delivered = ev[ev["event_type"] == "DELIVERED"].set_index("order_id")["occurred_at"]
    matured = delivered[delivered + pd.Timedelta(days=30) < T0].index
    returned = set(ev.loc[ev["event_type"] == "RETURN_REQUESTED", "order_id"])
    rate = len(returned & set(matured)) / len(matured)
    assert len(matured) == 48 and rate == pytest.approx(0.58, abs=0.01)
    since = T0 - pd.Timedelta(days=1500)
    assert _others_on(world, "device_id", r["device_id"], D.DEMO_1, since) == set()
    assert _others_on(world, "payment_token_id", r["payment_token_id"], D.DEMO_1, since) == set()
    assert _others_on(world, "address_id", r["address_id"], D.DEMO_1, since) == {D.DEMO_1_HOUSEHOLD}
    assert D.DEMO_1_HOUSEHOLD not in set(_confirmed_accounts(world)["account_id"])
    last = o.loc[(o["account_id"] == D.DEMO_1_HOUSEHOLD), "placed_at"].max()
    weight = 0.4 * 0.5 ** (((T0 - last) / pd.Timedelta(days=1)) / 45)
    assert weight == pytest.approx(0.13, abs=0.01)


def test_demo_1_order(requests):
    r = requests["ORD-DEMO-001"]
    value = sum(l["unit_price_inr"] * l["quantity"] for l in r["lines"]) * (1 - r["discount_pct"] / 100)
    assert value == pytest.approx(4500, abs=0.02)
    assert len({l["product_id"] for l in r["lines"]}) == 1 and len(r["lines"]) == 3


# ── Demo 2 ───────────────────────────────────────────────────────────────────
def test_demo_2_context(world, requests):
    r = requests["ORD-DEMO-002"]
    o = _visible_orders(world)
    assert round(_age_days(world, D.DEMO_2)) == 6
    assert (o["account_id"] == D.DEMO_2).sum() == 0
    truth = world["sim_ground_truth"].set_index("account_id")
    assert truth.loc[D.DEMO_2, "ring_id"] == "R4"

    device_peers = _others_on(world, "device_id", r["device_id"], D.DEMO_2, T0 - pd.Timedelta(days=30))
    assert len(device_peers) == 5
    conf = _confirmed_accounts(world)
    conf = conf[conf["account_id"].isin(device_peers)]
    assert conf["account_id"].nunique() == 3
    assert A.day_of(conf["occurred_at"].min().to_pydatetime()) >= 356
    assert A.day_of(conf["occurred_at"].max().to_pydatetime()) <= 362
    assert set(conf["attributes_json"]) == {'{"evidence_source":"WAREHOUSE_QC"}'}

    token_peers = _others_on(world, "payment_token_id", r["payment_token_id"], D.DEMO_2, T0 - pd.Timedelta(days=14))
    assert len(token_peers) == 3

    assert _others_on(world, "address_id", r["address_id"], D.DEMO_2, T0 - pd.Timedelta(days=3650)) == set()

    r4 = set(truth.index[truth["ring_id"] == "R4"]) - {D.DEMO_2}
    last_24h = o[o["account_id"].isin(r4) & (o["placed_at"] >= T0 - pd.Timedelta(hours=24))]
    assert len(last_24h) == 4
    lines = world["order_lines"][world["order_lines"]["order_id"].isin(last_24h["order_id"])]
    assert (lines["sku_id"] == r["lines"][0]["sku_id"]).sum() == 3


def test_demo_2_order(requests):
    r = requests["ORD-DEMO-002"]
    assert r["lines"][0]["unit_price_inr"] == 24000 and r["lines"][0]["category"] == "ELECTRONICS"
    assert r["delivery_speed"] == "EXPRESS" and r["payment_method"] == "PREPAID_CARD"
    assert r["device_id"] == identifier_id("DEVICE", A.R4_DEVICE_A)


# ── Demo 3 ───────────────────────────────────────────────────────────────────
def test_demo_3_history(world, requests):
    r = requests["ORD-DEMO-003"]
    o = _visible_orders(world)
    mine = o[o["account_id"] == D.DEMO_3]
    assert round(_age_days(world, D.DEMO_3)) == 240
    assert len(mine) == 7
    ev = world["order_events"]
    claims = ev[(ev["event_type"] == "CLAIM_FILED") & ev["order_id"].isin(mine["order_id"])]
    assert len(claims) == 1
    assert (T0 - claims["occurred_at"].iloc[0]) / pd.Timedelta(days=1) == pytest.approx(95)
    labels = world["order_labels"].set_index("order_id")
    assert labels.loc[claims["order_id"].iloc[0], "abuse_status"] == "UNRESOLVED"
    assert not ev[ev["order_id"].isin(mine["order_id"])]["event_type"].isin(
        ["ABUSE_CONFIRMED", "ABUSE_CLEARED", "QC_FLAGGED"]).any()

    # §11 as amended by the architect (deviation #26): shared concurrently with 3 other accounts in
    # the last 30 days, none of them confirmed abusive.
    confirmed = set(_confirmed_accounts(world)["account_id"])
    device_peers = _others_on(world, "device_id", r["device_id"], D.DEMO_3, T0 - pd.Timedelta(days=30))
    assert device_peers == set(D.DEMO_3_DEVICE_PEERS) and not device_peers & confirmed
    accounts = world["accounts"].set_index("account_id")
    for peer in D.DEMO_3_DEVICE_PEERS:
        assert (T0 - accounts.loc[peer, "created_at"]) / pd.Timedelta(days=1) <= 60
        peer_orders = o[o["account_id"] == peer]
        assert 1 <= len(peer_orders) <= 3
        assert (T0 - peer_orders["placed_at"].min()) / pd.Timedelta(days=1) <= 30
        assert not (peer_orders["address_id"] == r["address_id"]).any()
        assert not peer_orders["payment_token_id"].eq(r.get("payment_token_id")).any()

    address_peers = _others_on(world, "address_id", r["address_id"], D.DEMO_3, T0 - pd.Timedelta(days=3650))
    assert address_peers == {D.DEMO_3_ADDRESS_PEER} and address_peers <= confirmed
    last = o.loc[(o["account_id"] == D.DEMO_3_ADDRESS_PEER) & (o["address_id"] == r["address_id"]), "placed_at"].max()
    age = (T0 - last) / pd.Timedelta(days=1)
    assert age == pytest.approx(150) and 0.4 * 0.5 ** (age / 45) == pytest.approx(0.04, abs=0.005)


def test_demo_3_order(requests):
    r = requests["ORD-DEMO-003"]
    value = r["lines"][0]["unit_price_inr"] * (1 - r["discount_pct"] / 100)
    assert value == pytest.approx(12000, abs=0.01)
    assert r["lines"][0]["category"] == "FOOTWEAR" and r["discount_pct"] == 35
    assert r["payment_method"] == "COD" and r["payment_token_id"] is None
