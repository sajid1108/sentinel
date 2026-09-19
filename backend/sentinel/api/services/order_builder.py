"""The "Try an order" form's options (Phase 10 §A; GET /internal/demo/order-builder, DEMO_MODE only).

Everything the form offers comes from data, so nothing is typed free-hand in the browser and no id is
special-cased:

- placed_at: the presets' own (after the frozen history, before DEMO_CLOCK; #31).
- accounts: every preset's account; up to three seeded accounts whose stored decision carries a
  HOUSEHOLD_PATTERN or MULTI_TENANT_ADDRESS discounted link (most recent decision first); up to two accounts
  with no order before placed_at. Each carries its own most recent device, address and payment token from its
  HISTORY orders strictly before placed_at; an account with no order has no device or token, and gets a fresh
  address id, because a request cannot be built without one.
- devices / tokens: the account's own, a brand-new HMAC id made from a random value on every request, and
  "the ring's": the identifier of the preset with the strongest device (token) evidence, read with the same
  FeatureBuilder and §9.2 signal code that recorded the preset's decision. Frozen history (#30) makes that
  equal to the recorded decision's values; a test holds it to them.

Ground truth and the label tables are never read and the generator is never imported (P11).
"""
from __future__ import annotations

import json
import math
import secrets
import sqlite3
from typing import get_args

from sentinel.api.schemas import (BuilderAccount, BuilderIdentifierOption, Category, OrderBuilderResponse,
                                  ScoreOrderRequest)
from sentinel.api.services.order_view import account_history
from sentinel.api.services.scoring import ScoringService
from sentinel.db.models import parse_utc, utc_iso
from sentinel.features.graph_state import to_micros
from sentinel.features.identifiers import identifier_id
from sentinel.features.tabular_features import account_age_days
from sentinel.policy.guardrails import corroborating_signals

DISCOUNT_LABELS = {"HOUSEHOLD_PATTERN": "Shares a household address",
                   "MULTI_TENANT_ADDRESS": "Lives at a multi-tenant address"}
NEW_ACCOUNT_LABEL = "New account, no orders yet"
MAX_DISCOUNTED_ACCOUNTS = 3
MAX_NEW_ACCOUNTS = 2
OPTION_LABELS = {
    "DEVICE": {"OWN": "The account's own device", "NEW": "A brand-new device",
               "RING": "A device shared with the ring"},
    "PAYMENT_TOKEN": {"OWN": "The account's own token", "NEW": "A brand-new token", "RING": "The ring's card"},
}


def fresh_identifier(kind: str) -> str:
    """A never-seen hashed identifier: HMAC over a random value, never a placeholder."""
    return identifier_id(kind, secrets.token_hex(16))


def preset_label(preset: ScoreOrderRequest) -> str:
    return f"Account of preset {preset.order_id}"


# ── accounts ─────────────────────────────────────────────────────────────────
def _account(conn: sqlite3.Connection, account_id: str, label: str, t0_text: str) -> BuilderAccount:
    t0_us = to_micros(parse_utc(t0_text))
    state = account_history(conn, account_id, t0_text)
    acc = state.accounts.get(account_id)
    recent = conn.execute("SELECT device_id, address_id, payment_token_id FROM orders WHERE account_id = ? "
                          "AND source = 'HISTORY' AND placed_at < ? ORDER BY placed_at DESC, order_id DESC",
                          (account_id, t0_text)).fetchall()
    token = next((r["payment_token_id"] for r in recent if r["payment_token_id"] is not None), None)
    return BuilderAccount(
        account_id=account_id, label=label, account_age_days=math.floor(account_age_days(state, account_id, t0_us)),
        prior_orders=len(acc.orders) if acc else 0,
        device_id=recent[0]["device_id"] if recent else None,
        address_id=recent[0]["address_id"] if recent else fresh_identifier("ADDRESS"),
        payment_token_id=token)


def _discounted_accounts(conn: sqlite3.Connection, t0_text: str, exclude: set[str]) -> list[tuple[str, str]]:
    """(account_id, label) for seeded decisions with a household or multi-tenant discounted link, newest first."""
    found: list[tuple[str, str]] = []
    rows = conn.execute("SELECT o.account_id, d.discounted_links_json FROM decisions d JOIN orders o USING "
                        "(order_id) WHERE d.source = 'BACKTEST_REPLAY' AND o.placed_at < ? "
                        "ORDER BY o.placed_at DESC, o.order_id DESC", (t0_text,))
    for r in rows:
        if r["account_id"] in exclude or any(a == r["account_id"] for a, _ in found):
            continue
        reason = next((link["reason"] for link in json.loads(r["discounted_links_json"] or "[]")
                       if link["reason"] in DISCOUNT_LABELS), None)
        if reason is not None:
            found.append((r["account_id"], DISCOUNT_LABELS[reason]))
            if len(found) == MAX_DISCOUNTED_ACCOUNTS:
                break
    return found


def _new_accounts(conn: sqlite3.Connection, t0_text: str, exclude: set[str]) -> list[str]:
    rows = conn.execute("SELECT a.account_id FROM accounts a WHERE a.created_at < ? AND NOT EXISTS (SELECT 1 "
                        "FROM orders o WHERE o.account_id = a.account_id AND o.placed_at < ?) "
                        "ORDER BY a.account_id", (t0_text, t0_text))
    return [r["account_id"] for r in rows if r["account_id"] not in exclude][:MAX_NEW_ACCOUNTS]


# ── ring identifiers ─────────────────────────────────────────────────────────
def preset_evidence(scoring: ScoringService, preset: ScoreOrderRequest) -> tuple[float, float, int] | None:
    """(device confirmed-abuse weight, token signal weight, token other accounts 30 d) for the preset, as its
    decision records them (features_json and the PAYMENT_TOKEN signal). None when scoring is degraded."""
    if scoring.builder is None or scoring.models is None:
        return None
    inputs = scoring.builder.signal_inputs(preset, preset.placed_at)
    token = next(s for s in corroborating_signals(inputs) if s.signal == "PAYMENT_TOKEN")
    return inputs.device_confirmed_abuse_weight, token.weight, inputs.token_other_accounts_30d


def ring_identifiers(scoring: ScoringService, presets: list[ScoreOrderRequest]) -> tuple[str | None, str | None]:
    """The device of the preset with the highest device confirmed-abuse weight, and the token of the preset
    with the strongest token signal (weight, then other accounts). Ties keep the presets file's order; no
    evidence at all means no ring option."""
    scored = [(p, e) for p in presets if (e := preset_evidence(scoring, p)) is not None]
    device = max(scored, key=lambda pe: pe[1][0], default=None)
    with_token = [(p, e) for p, e in scored if p.payment_token_id is not None]
    token = max(with_token, key=lambda pe: (pe[1][1], pe[1][2]), default=None)
    return (device[0].device_id if device and device[1][0] > 0 else None,
            token[0].payment_token_id if token and (token[1][1] > 0 or token[1][2] > 0) else None)


def _options(kind: str, ring: str | None) -> list[BuilderIdentifierOption]:
    labels = OPTION_LABELS[kind]
    options = [BuilderIdentifierOption(option="OWN", label=labels["OWN"], identifier_id=None),
               BuilderIdentifierOption(option="NEW", label=labels["NEW"], identifier_id=fresh_identifier(kind))]
    if ring is not None:
        options.append(BuilderIdentifierOption(option="RING", label=labels["RING"], identifier_id=ring))
    return options


# ── response ─────────────────────────────────────────────────────────────────
def order_builder(conn: sqlite3.Connection, scoring: ScoringService,
                  presets: list[ScoreOrderRequest]) -> OrderBuilderResponse:
    """Caller holds the scoring lock (the FeatureBuilder's cache is not thread-safe)."""
    placed_at = max(p.placed_at for p in presets)
    t0_text = utc_iso(placed_at)
    accounts: list[BuilderAccount] = []
    for p in presets:
        if all(a.account_id != p.account_id for a in accounts):
            accounts.append(_account(conn, p.account_id, preset_label(p), t0_text))
    listed = {a.account_id for a in accounts}
    for account_id, label in _discounted_accounts(conn, t0_text, listed):
        accounts.append(_account(conn, account_id, label, t0_text))
    listed = {a.account_id for a in accounts}
    for account_id in _new_accounts(conn, t0_text, listed):
        accounts.append(_account(conn, account_id, NEW_ACCOUNT_LABEL, t0_text))
    ring_device, ring_token = ring_identifiers(scoring, presets)
    return OrderBuilderResponse(placed_at=placed_at, accounts=accounts,
                                devices=_options("DEVICE", ring_device),
                                tokens=_options("PAYMENT_TOKEN", ring_token),
                                categories=list(get_args(Category)))
