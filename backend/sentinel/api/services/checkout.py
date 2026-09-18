"""Public checkout outcome (§4 CheckoutOutcome and the customer-message table; Phase 7 brief §E).

The customer sees an outcome and a fixed message, nothing else: no score, reason, threshold, cost or action
name. ALLOW and MANUAL_REVIEW map to the same outcome and message, so their bodies differ only in order_id
and support_reference, which is a neutral digest of the decision id and encodes nothing about the action.
The outcome follows the decision's *current* action, so a reviewer override reaches the customer (§11 Demo 3).

Probe logging (§3 probe_events, §14.2): every scored call records how many times this device called in the
last 24 hours of the reviewer clock and how many distinct carts it tried. Log only: it never blocks and
never changes the response.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta

from sentinel.api.schemas import Action, CheckoutOutcome
from sentinel.db.models import utc_iso

CONFIRMED_MESSAGE = "Your order is confirmed."
PREPAID_MESSAGE = ("Please complete payment online to place this order. "
                   "Refunds are issued after the returned item is received.")
BLOCK_MESSAGE = "We're unable to process this order right now. Contact support with reference {ref}."
OUTCOMES: dict[Action, tuple[str, str]] = {
    Action.ALLOW: ("CONFIRMED", CONFIRMED_MESSAGE),
    Action.MANUAL_REVIEW: ("CONFIRMED", CONFIRMED_MESSAGE),
    Action.PREPAID_ONLY: ("PREPAID_PAYMENT_REQUIRED", PREPAID_MESSAGE),
    Action.BLOCK: ("UNABLE_TO_PROCESS", BLOCK_MESSAGE),
}
PROBE_WINDOW = timedelta(hours=24)


def support_reference(decision_id: str) -> str:
    """SUP- plus 8 hex characters of SHA-256 over the decision id: stable per decision, neutral."""
    return "SUP-" + hashlib.sha256(f"support:{decision_id}".encode("utf-8")).hexdigest()[:8].upper()


def checkout_outcome(order_id: str, decision_id: str, action: Action) -> CheckoutOutcome:
    outcome, message = OUTCOMES[action]
    ref = support_reference(decision_id)
    return CheckoutOutcome(order_id=order_id, outcome=outcome, customer_message=message.format(ref=ref),
                           support_reference=ref)


def log_probe(conn: sqlite3.Connection, *, now: datetime, device_id: str, account_id: str, order_id: str) -> None:
    """One probe_events row. Caller holds BEGIN IMMEDIATE.

    attempts_24h: this call plus the device's earlier calls in [now − 24 h, now).
    distinct_carts_24h: distinct order ids tried from the device in the window - this one, plus the device's
    live and demo orders placed in it (the table has no cart column; each call carries one order id).
    """
    since, until = utc_iso(now - PROBE_WINDOW), utc_iso(now)
    earlier = conn.execute("SELECT COUNT(*) FROM probe_events WHERE device_id = ? AND occurred_at >= ? "
                           "AND occurred_at < ?", (device_id, since, until)).fetchone()[0]
    carts = {r[0] for r in conn.execute(
        "SELECT order_id FROM orders WHERE device_id = ? AND source IN ('LIVE', 'DEMO') AND placed_at >= ? "
        "AND placed_at < ?", (device_id, since, until))} | {order_id}
    conn.execute("INSERT INTO probe_events (occurred_at, device_id, account_id, attempts_24h, distinct_carts_24h) "
                 "VALUES (?, ?, ?, ?, ?)", (until, device_id, account_id, earlier + 1, len(carts)))
