"""Label derivation from outcome events (§7.1). Offline only (P11).

label_definition_version "ld-1.0". Only events with occurred_at < as_of are visible.

Return label (matures at delivered + 30 d):
  1  RETURN_REQUESTED or EXCHANGE_REQUESTED within 30 d of DELIVERED
  0  delivered and the window closed with no return
  NULL  RTO, cancelled, not delivered, or window still open

Abuse label (matures at delivered + 60 d, or on resolution, whichever comes first):
  CONFIRMED  1     ABUSE_CONFIRMED within the adjudication window
  CLEARED    0     ABUSE_CLEARED within the adjudication window
  NO_CLAIM   0     window closed with no CLAIM_FILED or QC_FLAGGED (a return that passed QC included)
  UNRESOLVED NULL  window closed with a claim or QC flag but no resolution inside it (deviation #19)
  NOT_MATURED NULL window still open, or the order was never delivered (RTO/CANCELLED, deviation #18)
"""
from __future__ import annotations

import json
from dataclasses import astuple, dataclass
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

LABEL_DEFINITION_VERSION = "ld-1.0"
RETURN_WINDOW = timedelta(days=30)
ADJUDICATION_WINDOW = timedelta(days=60)
RETURN_EVENTS = frozenset({"RETURN_REQUESTED", "EXCHANGE_REQUESTED"})
DISPUTE_EVENTS = frozenset({"CLAIM_FILED", "QC_FLAGGED"})
RESOLUTION_EVENTS = frozenset({"ABUSE_CONFIRMED", "ABUSE_CLEARED"})

LABEL_COLUMNS = ["order_id", "return_label", "return_type", "returned_value_fraction", "abuse_status",
                 "abuse_label", "return_label_resolved_at", "abuse_label_resolved_at",
                 "label_definition_version"]


@dataclass(frozen=True)
class OrderLabel:
    order_id: str
    return_label: int | None
    return_type: str | None
    returned_value_fraction: float | None
    abuse_status: str
    abuse_label: int | None
    return_label_resolved_at: datetime | None
    abuse_label_resolved_at: datetime | None
    label_definition_version: str = LABEL_DEFINITION_VERSION


def label_order(order_id: str, events: Iterable[tuple[str, datetime, dict]], as_of: datetime) -> OrderLabel:
    """events: (event_type, occurred_at, attributes) for one order, in any order."""
    visible = sorted((e for e in events if e[1] < as_of), key=lambda e: e[1])
    delivered = next((t for typ, t, _ in visible if typ == "DELIVERED"), None)
    if delivered is None:
        return OrderLabel(order_id, None, None, None, "NOT_MATURED", None, None, None)

    return_end = delivered + RETURN_WINDOW
    if return_end < as_of:
        first_return = next(((typ, attrs) for typ, t, attrs in visible
                             if typ in RETURN_EVENTS and delivered <= t <= return_end), None)
        if first_return is None:
            ret = (0, "NONE", 0.0, return_end)
        else:
            typ, attrs = first_return
            fraction = float(attrs.get("returned_value_fraction", 1.0))
            kind = "EXCHANGE" if typ == "EXCHANGE_REQUESTED" else ("PARTIAL" if fraction < 1.0 else "FULL")
            ret = (1, kind, fraction, return_end)
    else:
        ret = (None, None, None, None)

    adjudication_end = delivered + ADJUDICATION_WINDOW
    resolution = next(((typ, t) for typ, t, _ in visible
                       if typ in RESOLUTION_EVENTS and t <= adjudication_end), None)
    if resolution is not None:
        typ, t = resolution
        abuse = ("CONFIRMED", 1, t) if typ == "ABUSE_CONFIRMED" else ("CLEARED", 0, t)
    elif not adjudication_end < as_of:
        abuse = ("NOT_MATURED", None, None)
    elif any(typ in DISPUTE_EVENTS and t <= adjudication_end for typ, t, _ in visible):
        abuse = ("UNRESOLVED", None, None)
    else:
        abuse = ("NO_CLAIM", 0, adjudication_end)

    return OrderLabel(order_id, ret[0], ret[1], ret[2], abuse[0], abuse[1], ret[3], abuse[2])


def derive_labels(order_ids: Iterable[str], order_events: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """One row per order id, derived from the order_events table only."""
    by_order: dict[str, list[tuple[str, datetime, dict]]] = {}
    ev = order_events.sort_values(["occurred_at", "event_id"], kind="stable")
    for order_id, typ, occurred_at, attrs in zip(ev["order_id"], ev["event_type"], ev["occurred_at"],
                                                  ev["attributes_json"]):
        by_order.setdefault(order_id, []).append((typ, occurred_at.to_pydatetime(), json.loads(attrs)))
    rows = [astuple(label_order(oid, by_order.get(oid, []), as_of)) for oid in sorted(order_ids)]
    df = pd.DataFrame(rows, columns=LABEL_COLUMNS)
    for col in ("return_label", "abuse_label"):
        df[col] = df[col].astype("Int64")
    df["returned_value_fraction"] = df["returned_value_fraction"].astype("float64")
    for col in ("return_label_resolved_at", "abuse_label_resolved_at"):
        df[col] = pd.Series(pd.to_datetime(list(df[col]), utc=True)).astype("datetime64[us, UTC]")
    return df
