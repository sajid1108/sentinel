"""§13.3 data checkpoint: determinism, prevalence, archetypes, rings, outputs."""
import hashlib
import hmac
import json

import numpy as np
import pandas as pd
import pytest

from sentinel.data import archetypes as A
from sentinel.data.generator import (EVENT_TYPES, OUTPUT_FILES, SEED, as_of_view, event_log_sha256,
                                     generate, identifier_id, stream_generators, summarize, write_outputs)
from sentinel.settings import DEMO_CLOCK, HMAC_SECRET

pytestmark = pytest.mark.slow

# C9: SHA-256 of the seed-20260901 world. Update deliberately, with the reason, when the generator changes.
REFERENCE_EVENT_LOG_SHA256 = "5b0966c392392ddf194bf59e369b6ab202619d2164cd533b5c5b2b9126f38559"


def _day(ts: pd.Series) -> pd.Series:
    return (ts - pd.Timestamp(A.SIM_START)) // pd.Timedelta(days=1) + 1


# ── Determinism ──────────────────────────────────────────────────────────────
def test_two_generations_have_identical_event_log_sha256(world):
    assert event_log_sha256(generate()) == event_log_sha256(world)


def test_c9_event_log_matches_stored_reference_hash(world):
    assert event_log_sha256(world) == REFERENCE_EVENT_LOG_SHA256


def test_different_seed_changes_the_world(world):
    assert event_log_sha256(generate(seed=SEED + 1)) != event_log_sha256(world)


def test_timeline_constants():
    assert A.day_start(366) + pd.Timedelta(hours=10, minutes=30) == DEMO_CLOCK
    assert A.HORIZON == A.day_start(441)


def test_streams_are_spawned_children_of_the_root_seed():
    streams = stream_generators()
    child = np.random.SeedSequence(SEED).spawn(len(streams))[1].spawn(2)[0]
    expected = np.random.Generator(np.random.PCG64(child)).random()
    assert streams["NORMAL"][0].random() == expected


def test_identifier_ids_are_hmac_prefixes(world):
    expected = hmac.new(HMAC_SECRET.encode(), b"DEVICE:RING-R4:device:A", hashlib.sha256).hexdigest()[:32]
    assert identifier_id("DEVICE", "RING-R4:device:A") == expected
    assert expected in set(world["identifiers"]["identifier_id"])
    assert world["identifiers"]["identifier_id"].str.fullmatch(r"[a-f0-9]{32}").all()


# ── Scale and prevalence (§5) ────────────────────────────────────────────────
def test_scale(world):
    assert 2700 <= len(world["accounts"]) <= 3300
    assert 10000 <= len(world["orders"]) <= 12000


def test_prevalence(world):
    s = summarize(world)
    assert 0.15 <= s["return_rate"] <= 0.25
    assert 0.03 <= s["confirmed_abuse_rate"] <= 0.06          # Fix 4
    assert s["rings"] == 4


def test_split_positives(world):
    merged = world["orders"][["order_id", "split"]].merge(world["order_labels"], on="order_id")
    positives = merged[merged["abuse_label"] == 1].groupby("split").size()
    assert positives.get("TEST", 0) >= 70 and positives.get("CALIBRATION", 0) >= 40


@pytest.mark.parametrize("archetype,lo,hi", [
    ("NORMAL", 2000, 2300), ("FREQUENT_RETURNER", 250, 250), ("HOUSEHOLD", 80, 160),
    ("OFFICE_HOSTEL_PG", 75, 180), ("REFURB_DEVICE", 60, 60), ("OPPORTUNISTIC", 85, 95),
    ("UNCONFIRMED_ABUSER", 30, 30), ("RING", 97, 97),
])
def test_archetype_account_counts(world, archetype, lo, hi):
    n = (world["sim_ground_truth"]["archetype"] == archetype).sum()
    assert lo <= n <= hi


def test_frequent_returners_return_often(orders_with_truth):
    fr = orders_with_truth[orders_with_truth["archetype"] == "FREQUENT_RETURNER"]
    assert 0.40 <= fr["return_label"].dropna().mean() <= 0.70
    assert not (fr["abuse_status"] == "CONFIRMED").any()


def test_frequent_returners_never_qc_flagged(world, orders_with_truth):
    fr_ids = orders_with_truth.loc[orders_with_truth["archetype"] == "FREQUENT_RETURNER", "order_id"]
    ev = world["order_events"]
    assert not ((ev["event_type"] == "QC_FLAGGED") & ev["order_id"].isin(fr_ids)).any()


def test_confirmed_abuse_only_on_abusive_archetypes(orders_with_truth):
    confirmed = orders_with_truth[orders_with_truth["abuse_status"] == "CONFIRMED"]
    assert set(confirmed["archetype"]) <= {"OPPORTUNISTIC", "RING"}


def test_unconfirmed_abusers_are_never_labelled_abusive(orders_with_truth):
    u = orders_with_truth[orders_with_truth["archetype"] == "UNCONFIRMED_ABUSER"]
    assert not (u["abuse_label"] == 1).any()
    assert (u["abuse_label"] == 0).sum() > 0.8 * len(u)


# ── Hard negatives ───────────────────────────────────────────────────────────
def test_households_share_addresses_and_some_share_tokens(world, orders_with_truth):
    hh = orders_with_truth[orders_with_truth["archetype"] == "HOUSEHOLD"]
    per_address = hh.groupby("address_id")["account_id"].nunique()
    assert (per_address >= 2).sum() >= 35
    per_token = hh.dropna(subset=["payment_token_id"]).groupby("payment_token_id")["account_id"].nunique()
    assert (per_token >= 2).sum() >= 10


def test_multi_tenant_addresses(world, orders_with_truth):
    mt = world["identifiers"][world["identifiers"]["is_multi_tenant"] == 1]
    assert len(mt) == 3
    assert (mt["kind"] == "ADDRESS").all() and mt["multi_tenant_set_at"].notna().all()
    site = orders_with_truth[orders_with_truth["address_id"].isin(mt["identifier_id"])]
    per_site = site.groupby("address_id")["account_id"].nunique()
    assert (per_site >= 25).all() and (per_site <= 60).all()
    # the flag is set part-way through, so early orders to the site predate it
    first = site.groupby("address_id")["placed_at"].min()
    assert (first < mt.set_index("identifier_id")["multi_tenant_set_at"]).all()


def _sequential_handovers(orders: pd.DataFrame) -> list[pd.Timedelta]:
    gaps = []
    for _, g in orders.groupby("device_id"):
        spans = g.groupby("account_id")["placed_at"].agg(["min", "max"]).sort_values("min")
        if len(spans) == 2 and spans["max"].iloc[0] < spans["min"].iloc[1]:
            gaps.append(spans["min"].iloc[1] - spans["max"].iloc[0])
    return gaps


def test_refurbished_devices_follow_an_inactive_owner(orders_with_truth):
    refurb_accounts = set(orders_with_truth.loc[orders_with_truth["archetype"] == "REFURB_DEVICE", "account_id"])
    devices = orders_with_truth.loc[orders_with_truth["account_id"].isin(refurb_accounts), "device_id"]
    gaps = _sequential_handovers(orders_with_truth[orders_with_truth["device_id"].isin(devices)])
    assert len(gaps) == 60
    assert min(gaps) >= pd.Timedelta(days=90)


def test_hostel_has_sequential_device_reuse(orders_with_truth):
    site = orders_with_truth[orders_with_truth["archetype"] == "OFFICE_HOSTEL_PG"]
    gaps = _sequential_handovers(site)
    assert len(gaps) >= 3
    assert min(gaps) >= pd.Timedelta(days=60)


# ── Rings ────────────────────────────────────────────────────────────────────
def test_ring_sizes(world):
    truth = world["sim_ground_truth"]
    synthetic = truth[truth["archetype"] == "RING"]
    assert synthetic.groupby("ring_id").size().to_dict() == {"R1": 24, "R2": 36, "R3": 30, "R4": 7}


def test_r3_exists_only_in_test_dates(world, orders_with_truth):
    r3 = orders_with_truth[orders_with_truth["ring_id"] == "R3"]
    days = _day(r3["placed_at"])
    assert days.between(306, 365).all() and (r3["split"] == "TEST").all()
    # dormant recruits may be old accounts, but none has an order before TEST
    assert not orders_with_truth[orders_with_truth["account_id"].isin(r3["account_id"])
                                 & (_day(orders_with_truth["placed_at"]) < 306)].shape[0]
    shared = set(r3["device_id"]) | set(r3["payment_token_id"].dropna())
    earlier = orders_with_truth[_day(orders_with_truth["placed_at"]) < 306]
    assert shared.isdisjoint(set(earlier["device_id"]) | set(earlier["payment_token_id"].dropna()))


@pytest.mark.parametrize("ring_id,start,end", [("R1", 40, 90), ("R2", 170, 260), ("R3", 315, 345)])
def test_ring_activity_windows(orders_with_truth, ring_id, start, end):
    ring = orders_with_truth[orders_with_truth["ring_id"] == ring_id]
    shared = ring.groupby("device_id")["account_id"].nunique()
    shared_devices = shared[shared >= 3].index
    days = _day(ring.loc[ring["device_id"].isin(shared_devices), "placed_at"])
    assert len(days) > 0 and days.between(start, end).all()


def test_r4_three_members_confirmed_by_d362_and_no_others_before_demo_clock(world, orders_with_truth):
    r4 = orders_with_truth[orders_with_truth["ring_id"] == "R4"]
    ev = world["order_events"]
    conf = ev[(ev["event_type"] == "ABUSE_CONFIRMED") & ev["order_id"].isin(r4["order_id"])]
    conf = conf.merge(r4[["order_id", "account_id"]], on="order_id")
    by_d362 = conf[conf["occurred_at"] < pd.Timestamp(A.day_start(363))]
    assert by_d362["account_id"].nunique() == 3
    assert _day(by_d362["occurred_at"]).between(356, 362).all()
    before_clock = conf[conf["occurred_at"] < pd.Timestamp(DEMO_CLOCK)]
    assert len(before_clock) == 3


def test_rings_share_devices_and_tokens_but_rotate_addresses(orders_with_truth):
    for ring_id, g in orders_with_truth[orders_with_truth["ring_id"].notna()].groupby("ring_id"):
        members = g["account_id"].nunique()
        assert g.groupby("device_id")["account_id"].nunique().max() >= 2, ring_id
        assert g.dropna(subset=["payment_token_id"]).groupby("payment_token_id")["account_id"].nunique().max() >= 3
        assert g["address_id"].nunique() >= members
        assert g.groupby("address_id")["account_id"].nunique().max() == 1


def test_ring_cover_orders_are_low_value_and_kept(world, orders_with_truth):
    ring = orders_with_truth[(orders_with_truth["archetype"] == "RING")]
    delivered_only = world["order_events"].groupby("order_id")["event_type"].agg(tuple)
    kept = ring[ring["order_id"].map(delivered_only).map(lambda t: t == ("DELIVERED",))]
    cheap = kept[kept["order_value_inr"] < 1600]
    assert 0.10 <= len(cheap) / len(ring) <= 0.35


# ── Outputs and schema ───────────────────────────────────────────────────────
ORDER_COLUMNS = ["order_id", "account_id", "placed_at", "order_value_inr", "discount_pct", "n_items",
                 "n_variants_same_product", "primary_category", "delivery_speed", "payment_method",
                 "device_id", "address_id", "payment_token_id", "source", "split"]


def test_tables_match_schema_columns_and_carry_no_features(world):
    assert list(world["orders"].columns) == ORDER_COLUMNS
    assert list(world["order_events"].columns) == ["event_id", "order_id", "event_type", "occurred_at",
                                                   "attributes_json"]
    assert list(world["accounts"].columns) == ["account_id", "created_at", "source"]
    assert list(world["identifiers"].columns) == ["identifier_id", "kind", "is_multi_tenant",
                                                  "multi_tenant_set_at", "display_label"]
    assert list(world["order_lines"].columns) == ["order_id", "line_no", "sku_id", "product_id", "variant",
                                                  "category", "unit_price_inr", "quantity"]
    assert list(world["sim_ground_truth"].columns) == ["account_id", "archetype", "ring_id"]


def test_schema_constraints(world):
    o, ev = world["orders"], world["order_events"]
    assert o["order_id"].str.fullmatch(r"ORD-[A-Z0-9-]{3,40}").all()
    assert o["account_id"].str.fullmatch(r"ACC-[A-Z0-9-]{3,40}").all()
    assert (o["order_value_inr"] > 0).all() and o["discount_pct"].between(0, 90).all()
    assert (o["n_items"] >= 1).all()
    assert set(o["primary_category"]) <= set(A.CATEGORIES)
    assert set(o["payment_method"]) <= {"PREPAID_CARD", "PREPAID_UPI", "COD"}
    assert set(o["delivery_speed"]) <= {"STANDARD", "EXPRESS"}
    assert ((o["payment_method"] == "COD") == o["payment_token_id"].isna()).all()
    assert _day(o["placed_at"]).between(1, 365).all()
    assert (o["source"] == "HISTORY").all()
    assert set(world["accounts"]["source"]) == {"SYNTHETIC", "DEMO"}
    assert set(ev["event_type"]) <= set(EVENT_TYPES)
    assert (ev["occurred_at"] < pd.Timestamp(A.HORIZON)).all()
    assert ev["attributes_json"].map(lambda s: isinstance(json.loads(s), dict)).all()
    idents = set(world["identifiers"]["identifier_id"])
    assert set(o["device_id"]) | set(o["address_id"]) | set(o["payment_token_id"].dropna()) <= idents


def test_split_column_follows_placement_day(world):
    o = world["orders"].merge(world["sim_ground_truth"], on="account_id")
    history = o[o["archetype"] != "DEMO"]
    assert (history["split"] == _day(history["placed_at"]).map(A.split_for_day)).all()
    assert (o.loc[o["archetype"] == "DEMO", "split"] == "RECENT").all()          # Fix 6


def test_event_ids_follow_time_order(world):
    ev = world["order_events"]
    assert ev["event_id"].is_monotonic_increasing and ev["occurred_at"].is_monotonic_increasing


def test_write_outputs_round_trip(world, tmp_path):
    paths = write_outputs(world, tmp_path)
    assert {p.name for p in paths.values()} == set(OUTPUT_FILES.values())
    for name, path in paths.items():
        back = pd.read_parquet(path)
        pd.testing.assert_frame_equal(back, world[name], check_dtype=False)


def test_as_of_view_has_nothing_at_or_after_demo_clock(world):
    view = as_of_view(world)
    clock = pd.Timestamp(DEMO_CLOCK)
    assert (view["order_events"]["occurred_at"] < clock).all()
    assert (view["orders"]["placed_at"] < clock).all()
    assert (view["accounts"]["created_at"] < clock).all()
    assert len(view["order_events"]) < len(world["order_events"])
    assert set(view["order_lines"]["order_id"]) <= set(view["orders"]["order_id"])
    assert "sim_ground_truth" not in view and "order_labels" not in view


def test_as_of_view_hides_multi_tenant_flags_set_later(world):
    set_at = world["identifiers"]["multi_tenant_set_at"].dropna()
    early = set_at.min()
    view = as_of_view(world, early.to_pydatetime())
    assert view["identifiers"]["is_multi_tenant"].sum() == 0
    assert view["identifiers"]["multi_tenant_set_at"].isna().all()


# ── Labels on the generated world (§7.1) ─────────────────────────────────────
def test_labels_are_rederivable_from_events_alone(world):
    from sentinel.data.labels import derive_labels
    again = derive_labels(world["orders"]["order_id"], world["order_events"][
        ["event_id", "order_id", "event_type", "occurred_at", "attributes_json"]], A.HORIZON)
    pd.testing.assert_frame_equal(again, world["order_labels"])


def test_world_label_combinations(world):
    lab = world["order_labels"]
    assert len(lab) == len(world["orders"]) and (lab["label_definition_version"] == "ld-1.0").all()
    assert ((lab["return_label"] == 0) & (lab["abuse_label"] == 1)).sum() > 0
    assert ((lab["return_label"] == 1) & (lab["abuse_label"] == 1)).sum() > 0
    assert ((lab["return_label"] == 1) & (lab["abuse_label"] == 0)).sum() > 0
    assert (lab["abuse_status"] == "UNRESOLVED").sum() > 0
    assert lab.loc[lab["abuse_status"].isin(["UNRESOLVED", "NOT_MATURED"]), "abuse_label"].isna().all()
    assert (lab.loc[lab["abuse_status"] == "CONFIRMED", "abuse_label"] == 1).all()
    assert (lab.loc[lab["abuse_status"].isin(["CLEARED", "NO_CLAIM"]), "abuse_label"] == 0).all()


def test_rto_and_cancelled_orders_have_null_labels(world):
    ev = world["order_events"]
    excluded = set(ev.loc[ev["event_type"].isin(["RTO", "CANCELLED"]), "order_id"])
    assert excluded
    lab = world["order_labels"][world["order_labels"]["order_id"].isin(excluded)]
    assert lab["return_label"].isna().all() and lab["abuse_label"].isna().all()
    assert (lab["abuse_status"] == "NOT_MATURED").all()


def test_every_delivered_order_matures_by_the_horizon(world):
    ev = world["order_events"]
    delivered = set(ev.loc[ev["event_type"] == "DELIVERED", "order_id"])
    lab = world["order_labels"][world["order_labels"]["order_id"].isin(delivered)]
    assert lab["return_label"].notna().all()
    assert not (lab["abuse_status"] == "NOT_MATURED").any()
