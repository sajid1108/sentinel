"""§7.1 label definitions (ld-1.0), on hand-built event lists."""
from datetime import timedelta

import pandas as pd
import pytest

from sentinel.data.labels import LABEL_DEFINITION_VERSION, derive_labels, label_order
from sentinel.settings import DEMO_CLOCK

PLACED = DEMO_CLOCK - timedelta(days=200)
DELIVERED = PLACED + timedelta(days=3)
LATE = DELIVERED + timedelta(days=100)          # every window closed


def d(days: float):
    return DELIVERED + timedelta(days=days)


def label(events, as_of=LATE):
    return label_order("ORD-T", [("DELIVERED", DELIVERED, {})] + events, as_of)


def test_no_return_no_claim():
    lab = label([])
    assert (lab.return_label, lab.return_type, lab.returned_value_fraction) == (0, "NONE", 0.0)
    assert (lab.abuse_status, lab.abuse_label) == ("NO_CLAIM", 0)
    assert lab.return_label_resolved_at == d(30) and lab.abuse_label_resolved_at == d(60)
    assert lab.label_definition_version == LABEL_DEFINITION_VERSION == "ld-1.0"


def test_full_partial_and_exchange_returns():
    full = label([("RETURN_REQUESTED", d(5), {"returned_value_fraction": 1.0})])
    partial = label([("RETURN_REQUESTED", d(5), {"returned_value_fraction": 0.5})])
    exchange = label([("EXCHANGE_REQUESTED", d(5), {"returned_value_fraction": 1.0})])
    assert (full.return_label, full.return_type) == (1, "FULL")
    assert (partial.return_label, partial.return_type, partial.returned_value_fraction) == (1, "PARTIAL", 0.5)
    assert (exchange.return_label, exchange.return_type) == (1, "EXCHANGE")


def test_return_after_30_days_does_not_count():
    lab = label([("RETURN_REQUESTED", d(31), {"returned_value_fraction": 1.0})])
    assert lab.return_label == 0


def test_return_passed_qc_is_abuse_zero():
    lab = label([("RETURN_REQUESTED", d(5), {"returned_value_fraction": 1.0}),
                 ("QC_PASSED", d(8), {})])
    assert (lab.return_label, lab.abuse_status, lab.abuse_label) == (1, "NO_CLAIM", 0)


def test_return_window_not_closed_is_null():
    lab = label([("RETURN_REQUESTED", d(5), {"returned_value_fraction": 1.0})], as_of=d(20))
    assert (lab.return_label, lab.return_type, lab.return_label_resolved_at) == (None, None, None)
    assert (lab.abuse_status, lab.abuse_label) == ("NOT_MATURED", None)


@pytest.mark.parametrize("terminal", ["RTO", "CANCELLED"])
def test_rto_and_cancelled_are_excluded(terminal):
    lab = label_order("ORD-T", [(terminal, PLACED + timedelta(days=2), {})], LATE)
    assert (lab.return_label, lab.return_type) == (None, None)
    assert (lab.abuse_status, lab.abuse_label) == ("NOT_MATURED", None)


def test_confirmed_claim_is_return_zero_abuse_one():
    lab = label([("CLAIM_FILED", d(1), {"claim_type": "ITEM_NOT_RECEIVED"}),
                 ("CARRIER_EVIDENCE", d(6), {"contradicts_claim": True}),
                 ("ABUSE_CONFIRMED", d(20), {})])
    assert (lab.return_label, lab.abuse_status, lab.abuse_label) == (0, "CONFIRMED", 1)
    assert lab.abuse_label_resolved_at == d(20)


def test_confirmation_resolves_before_the_window_closes():
    lab = label([("QC_FLAGGED", d(10), {}), ("ABUSE_CONFIRMED", d(20), {})], as_of=d(25))
    assert (lab.abuse_status, lab.abuse_label) == ("CONFIRMED", 1)


def test_cleared():
    lab = label([("CLAIM_FILED", d(1), {}), ("ABUSE_CLEARED", d(20), {})])
    assert (lab.abuse_status, lab.abuse_label) == ("CLEARED", 0)


def test_unresolved_claim_is_excluded():
    lab = label([("CLAIM_FILED", d(1), {}), ("CARRIER_EVIDENCE", d(6), {})])
    assert (lab.abuse_status, lab.abuse_label, lab.abuse_label_resolved_at) == ("UNRESOLVED", None, None)


def test_uninvestigated_qc_flag_is_unresolved():
    lab = label([("RETURN_REQUESTED", d(5), {"returned_value_fraction": 1.0}), ("QC_FLAGGED", d(9), {})])
    assert (lab.return_label, lab.abuse_status, lab.abuse_label) == (1, "UNRESOLVED", None)


def test_resolution_after_adjudication_window_is_unresolved():
    lab = label([("QC_FLAGGED", d(40), {}), ("ABUSE_CONFIRMED", d(61), {})])
    assert (lab.abuse_status, lab.abuse_label) == ("UNRESOLVED", None)


def test_open_claim_inside_window_is_not_matured():
    lab = label([("CLAIM_FILED", d(1), {})], as_of=d(30))
    assert (lab.abuse_status, lab.abuse_label) == ("NOT_MATURED", None)


def test_event_at_exactly_as_of_is_invisible():
    lab = label([("CLAIM_FILED", d(1), {}), ("ABUSE_CONFIRMED", d(20), {})], as_of=d(20))
    assert lab.abuse_status == "NOT_MATURED"


def test_derive_labels_from_event_table():
    events = pd.DataFrame({
        "event_id": [1, 2, 3],
        "order_id": ["ORD-A", "ORD-A", "ORD-B"],
        "event_type": ["DELIVERED", "RETURN_REQUESTED", "RTO"],
        "occurred_at": pd.to_datetime([DELIVERED, d(2), DELIVERED], utc=True),
        "attributes_json": ["{}", '{"returned_value_fraction":1.0}', "{}"],
    })
    df = derive_labels(["ORD-B", "ORD-A", "ORD-C"], events, LATE).set_index("order_id")
    assert df.loc["ORD-A", "return_label"] == 1 and df.loc["ORD-A", "abuse_label"] == 0
    assert pd.isna(df.loc["ORD-B", "return_label"]) and df.loc["ORD-B", "abuse_status"] == "NOT_MATURED"
    assert df.loc["ORD-C", "abuse_status"] == "NOT_MATURED"
    assert str(df["abuse_label"].dtype) == "Int64"


# ── C8: label edge cases (Phase 2 review) ────────────────────────────────────
def test_c8_claim_after_adjudication_window_is_no_claim():
    lab = label([("CLAIM_FILED", d(61), {"claim_type": "ITEM_NOT_RECEIVED"})])
    assert (lab.abuse_status, lab.abuse_label) == ("NO_CLAIM", 0)


@pytest.mark.parametrize("first,second,expected", [
    ("RETURN_REQUESTED", "EXCHANGE_REQUESTED", "FULL"),
    ("EXCHANGE_REQUESTED", "RETURN_REQUESTED", "EXCHANGE"),
])
def test_c8_earliest_return_event_decides_return_type(first, second, expected):
    # listed out of time order on purpose: the earliest occurred_at decides
    lab = label([(second, d(12), {"returned_value_fraction": 1.0}),
                 (first, d(4), {"returned_value_fraction": 1.0})])
    assert (lab.return_label, lab.return_type) == (1, expected)


def test_c8_first_resolution_wins():
    lab = label([("QC_FLAGGED", d(8), {}), ("ABUSE_CLEARED", d(20), {}), ("ABUSE_CONFIRMED", d(40), {})])
    assert (lab.abuse_status, lab.abuse_label, lab.abuse_label_resolved_at) == ("CLEARED", 0, d(20))


def test_c8_as_of_exactly_at_return_window_end_is_null():
    lab = label([], as_of=d(30))
    assert (lab.return_label, lab.return_type, lab.return_label_resolved_at) == (None, None, None)


def test_c8_return_without_fraction_defaults_to_full():
    lab = label([("RETURN_REQUESTED", d(5), {})])
    assert (lab.return_label, lab.return_type, lab.returned_value_fraction) == (1, "FULL", 1.0)
