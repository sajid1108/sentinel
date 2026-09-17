"""§7.2 P3-P5, P7 and the §6.1 reliability, decay and exclusion rules, on hand-built worlds."""
from datetime import timedelta

import pytest

from sentinel.features.graph_state import to_micros, visible
from sentinel.features.identifiers import PLACEHOLDER_IDS
from tests.leakage.mini_world import DAY, T0, MiniWorld, builder_at, features_at, offline_features

HOUR = timedelta(hours=1)


# ── P3: strict < on t0 ───────────────────────────────────────────────────────
def test_p3_visible_helper_is_strict():
    t0 = to_micros(T0)
    assert visible(t0 - 1, t0) and not visible(t0, t0) and not visible(None, t0)


@pytest.mark.parametrize("offset,expected", [(timedelta(0), 0), (-timedelta(microseconds=1), 1)])
def test_p3_event_at_exactly_t0_is_invisible(offset, expected):
    w = MiniWorld()
    w.order("ORD-OLD", "ACC-AAA", T0 - 20 * DAY)
    w.event("ORD-OLD", "DELIVERED", T0 - 17 * DAY)
    w.event("ORD-OLD", "CLAIM_FILED", T0 + offset)
    now = w.order("ORD-NOW", "ACC-AAA", T0)
    assert features_at(w, now)["prior_suspicious_claims_180d"] == expected
    assert offline_features(w)["ORD-NOW"]["prior_suspicious_claims_180d"] == expected


def test_p3_order_placed_at_the_same_instant_is_invisible():
    w = MiniWorld()
    device = w.ident("DEVICE", "shared")
    w.order("ORD-AAA", "ACC-AAA", T0 - 2 * DAY, device=device)
    w.order("ORD-BBB", "ACC-BBB", T0, device=device)
    w.order("ORD-CCC", "ACC-CCC", T0, device=device)
    offline = offline_features(w)
    assert offline["ORD-BBB"]["device_other_accounts_30d"] == 1          # sees A, not C
    assert offline["ORD-CCC"]["device_other_accounts_30d"] == 1          # sees A, not B
    assert offline["ORD-BBB"]["identifier_reuse_velocity_7d"] == 1


def test_p3_own_edges_are_added_after_features():
    w = MiniWorld()
    first = w.order("ORD-AAA", "ACC-AAA", T0)
    f = offline_features(w)["ORD-AAA"]
    assert f["prior_orders"] == 0 and f["new_device_for_account"] == 1 and f["component_size_reliable_90d"] == 1
    assert features_at(w, first) == f


# ── P4: confirmation time, not order time ────────────────────────────────────
@pytest.mark.parametrize("confirmed_at,counted", [(T0 + DAY, False), (T0, False), (T0 - DAY, True)])
def test_p4_neighbour_counts_only_if_confirmed_before_t0(confirmed_at, counted):
    w = MiniWorld()
    device = w.ident("DEVICE", "shared")
    w.order("ORD-BAD", "ACC-BAD", T0 - 20 * DAY, device=device)
    w.event("ORD-BAD", "DELIVERED", T0 - 17 * DAY)
    w.event("ORD-BAD", "QC_FLAGGED", T0 - 5 * DAY)
    w.event("ORD-BAD", "ABUSE_CONFIRMED", confirmed_at)
    now = w.order("ORD-NOW", "ACC-NOW", T0, device=device)
    f = features_at(w, now)
    expected_weight = 0.8 * 0.5 ** (20 / 30)
    assert f["device_confirmed_abuse_weight"] == (pytest.approx(expected_weight) if counted else 0)
    assert f["component_abuse_ratio_smoothed"] == pytest.approx((1 + counted) / (2 + 10))
    assert f["confirmed_abuse_proximity"] == (0.5 if counted else 0.0)


# ── P5: matured history only ─────────────────────────────────────────────────
def test_p5_open_return_window_is_not_counted():
    w = MiniWorld()
    w.order("ORD-OPEN", "ACC-AAA", T0 - 13 * DAY)
    w.event("ORD-OPEN", "DELIVERED", T0 - 10 * DAY)
    w.event("ORD-OPEN", "RETURN_REQUESTED", T0 + 5 * DAY, returned_value_fraction=1.0)
    now = w.order("ORD-NOW", "ACC-AAA", T0)
    f = features_at(w, now)
    assert f["matured_return_rate_smoothed"] == pytest.approx(2 / 10)
    assert f["prior_returns_90d"] == 0


def test_p5_matured_return_is_counted():
    w = MiniWorld()
    w.order("ORD-OLD", "ACC-AAA", T0 - 45 * DAY)
    w.event("ORD-OLD", "DELIVERED", T0 - 42 * DAY)
    w.event("ORD-OLD", "RETURN_REQUESTED", T0 - 35 * DAY, returned_value_fraction=1.0)
    now = w.order("ORD-NOW", "ACC-AAA", T0)
    f = features_at(w, now)
    assert f["matured_return_rate_smoothed"] == pytest.approx(3 / 11)
    assert f["prior_returns_90d"] == 1


# ── P7: point-in-time multi-tenant flag ──────────────────────────────────────
@pytest.mark.parametrize("set_at,reliability", [(T0 + DAY, 0.4), (T0, 0.4), (T0 - DAY, 0.1)])
def test_p7_multi_tenant_flag_trusted_only_before_t0(set_at, reliability):
    w = MiniWorld()
    address = w.ident("ADDRESS", "hostel", multi_tenant_set_at=set_at)
    w.order("ORD-AAA", "ACC-AAA", T0 - 3 * DAY, address=address)
    now = w.order("ORD-NOW", "ACC-NOW", T0, address=address)
    f = features_at(w, now)
    assert f["address_other_accounts_weighted_30d"] == pytest.approx(reliability * 0.5 ** (3 / 45))
    b = builder_at(w, T0)
    assert b.signal_inputs(w.request(now)).address_is_multi_tenant == (reliability == 0.1)
    assert f["component_size_reliable_90d"] == (2 if reliability == 0.4 else 1)       # multi-tenant excluded


# ── §6.1 reliability, decay, exclusions ──────────────────────────────────────
def test_sequential_device_use_gets_reliability_0_2():
    w = MiniWorld()
    device = w.ident("DEVICE", "refurb")
    w.order("ORD-OWN", "ACC-OWN", T0 - 100 * DAY, device=device)
    now = w.order("ORD-NEW", "ACC-NEW", T0, device=device)
    b = builder_at(w, T0)
    links = b.discounted_links(w.request(now))
    assert [(d.kind, d.reason) for d in links] == [("DEVICE", "SEQUENTIAL_DEVICE_USE")]
    assert links[0].weight == pytest.approx(0.2 * 0.5 ** (100 / 30), abs=1e-4)
    f = b.features_for_request(w.request(now))
    assert f["device_other_accounts_30d"] == 0 and f["component_size_reliable_90d"] == 1


def test_concurrent_device_use_gets_reliability_0_8():
    w = MiniWorld()
    device = w.ident("DEVICE", "shared")
    w.order("ORD-AAA", "ACC-AAA", T0 - 10 * DAY, device=device)
    now = w.order("ORD-NOW", "ACC-NOW", T0, device=device)
    b = builder_at(w, T0)
    assert b.signal_inputs(w.request(now)).device_weight == pytest.approx(0.8 * 0.5 ** (10 / 30))
    assert b.discounted_links(w.request(now)) == []


def test_stale_relationship_is_discounted_and_excluded_from_component():
    w = MiniWorld()
    token = w.ident("PAYMENT_TOKEN", "card")
    w.order("ORD-AAA", "ACC-AAA", T0 - 120 * DAY, token=token)
    now = w.order("ORD-NOW", "ACC-NOW", T0, token=token)
    b = builder_at(w, T0)
    links = b.discounted_links(w.request(now))
    assert [(d.kind, d.reason) for d in links] == [("PAYMENT_TOKEN", "STALE_RELATIONSHIP")]
    assert b.features_for_request(w.request(now))["component_size_reliable_90d"] == 1


def test_high_fanout_address_excluded_from_components():
    w = MiniWorld()
    address = w.ident("ADDRESS", "mailroom")
    for i in range(26):
        w.order(f"ORD-F{i:03d}", f"ACC-F{i:03d}", T0 - DAY, address=address)
    now = w.order("ORD-NOW", "ACC-NOW", T0, address=address)
    b = builder_at(w, T0)
    f = b.features_for_request(w.request(now))
    assert f["component_size_reliable_90d"] == 1 and f["address_other_accounts_weighted_30d"] == 0
    assert [d.reason for d in b.discounted_links(w.request(now))] == ["HIGH_FANOUT_IDENTIFIER"]


def test_small_shared_address_is_reliable_and_household_pattern():
    w = MiniWorld()
    address = w.ident("ADDRESS", "family-home")
    for i in range(3):
        w.order(f"ORD-H{i}", f"ACC-H{i:02d}", T0 - DAY, address=address)
    now = w.order("ORD-NOW", "ACC-NOW", T0, address=address)
    b = builder_at(w, T0)
    assert b.features_for_request(w.request(now))["component_size_reliable_90d"] == 4
    assert [d.reason for d in b.discounted_links(w.request(now))] == ["HOUSEHOLD_PATTERN"]


@pytest.mark.parametrize("placeholder", ["0" * 32, sorted(PLACEHOLDER_IDS - {"0" * 32})[0]])
def test_placeholder_identifiers_never_become_nodes(placeholder):
    w = MiniWorld()
    w.raw_ident("DEVICE", placeholder)
    w.order("ORD-AAA", "ACC-AAA", T0 - DAY, device=placeholder)
    now = w.order("ORD-NOW", "ACC-NOW", T0, device=placeholder)
    b = builder_at(w, T0 + HOUR)
    assert f"DEV:{placeholder}" not in b.state.graph
    b = builder_at(w, T0)
    f = b.features_for_request(w.request(now))
    assert f["device_other_accounts_30d"] == 0 and f["component_size_reliable_90d"] == 1


def test_bfs_cap_respected():
    w = MiniWorld()
    token = w.ident("PAYMENT_TOKEN", "shared-card")
    for i in range(250):
        w.order(f"ORD-C{i:03d}", f"ACC-C{i:03d}", T0 - HOUR, token=token)
    now = w.order("ORD-NOW", "ACC-NOW", T0, token=token)
    f = features_at(w, now)
    assert f["component_size_reliable_90d"] == 200
    assert f["token_other_accounts_30d"] == 250


def test_features_for_request_refuses_state_ahead_of_t0():
    w = MiniWorld()
    w.order("ORD-AAA", "ACC-AAA", T0 + HOUR)
    now = w.order("ORD-NOW", "ACC-NOW", T0)
    with pytest.raises(ValueError):
        builder_at(w, T0 + DAY).features_for_request(w.request(now))


def test_cod_order_uses_accounts_prior_tokens():
    w = MiniWorld()
    token = w.ident("PAYMENT_TOKEN", "shared-card")
    w.order("ORD-AAA", "ACC-AAA", T0 - 5 * DAY, token=token)
    w.order("ORD-BBB", "ACC-BBB", T0 - 4 * DAY, token=token)
    w.order("ORD-OLD", "ACC-NOW", T0 - 3 * DAY, token=token)
    now = w.order("ORD-NOW", "ACC-NOW", T0, token=None)
    assert features_at(w, now)["token_other_accounts_30d"] == 2
