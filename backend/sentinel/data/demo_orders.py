"""The three deterministic demo scenarios (§11).

demo_population() hand-authors the demo accounts, their supporting accounts and every
history event. Nothing here is sampled, so the histories cannot be perturbed by the RNG.
Demo 2's ring context (ring R4) is scheduled in archetypes.gen_ring_r4.

demo_requests() builds the three ScoreOrderRequest payloads, placed at DEMO_CLOCK - 5 min.
The demo orders themselves are not part of the generated history; they are scored live.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sentinel.data import archetypes as A
from sentinel.data.archetypes import (ANCHOR_PRODUCTS, AccountSpec, Line, OrderPlan, Population,
                                      Product, ScriptedEvent, at, make_line)
from sentinel.settings import DEMO_CLOCK, HMAC_SECRET

DEMO_PLACED_AT = DEMO_CLOCK - timedelta(minutes=5)

DEMO_1, DEMO_2, DEMO_3 = "ACC-DEMO-001", "ACC-DEMO-002", "ACC-DEMO-003"
DEMO_1_HOUSEHOLD = "ACC-DEMO-001-HH"          # shares Demo 1's address, no abuse
DEMO_3_DEVICE_PEER = "ACC-DEMO-003-DEV"       # shares Demo 3's device concurrently, not confirmed
DEMO_3_ADDRESS_PEER = "ACC-DEMO-003-ADR"      # Demo 3's address, confirmed abusive long ago

# Synthetic identifier values (hashed by the generator)
D1_DEVICE, D1_ADDRESS, D1_UPI = "DEMO-001:device", "DEMO-001:address", "DEMO-001:upi"
D2_ADDRESS = "DEMO-002:address"               # unique: the ring rotates addresses
D3_DEVICE, D3_ADDRESS, D3_UPI = "DEMO-003:device", "DEMO-003:address", "DEMO-003:upi"

# Hand-authored history products
_DRESS_2 = Product("PRD-APPAREL-D02", "APPAREL", 1999.0, ("M", "L"))
_SHOES = Product("PRD-FOOTWEAR-D02", "FOOTWEAR", 2499.0, ("UK8",))
_CANVAS_SHOES = Product("PRD-FOOTWEAR-D03", "FOOTWEAR", 1499.0, ("UK8",))    # Demo 1: CLV ~₹30,000 (§11)
_TOP = Product("PRD-APPAREL-D03", "APPAREL", 1299.0, ("M",))
_BELT = Product("PRD-ACCESSORIES-D01", "ACCESSORIES", 899.0, ("TAN",))
_KETTLE = Product("PRD-HOME-D01", "HOME", 1799.0, ("STD",))
_EARPHONES = Product("PRD-ELECTRONICS-D01", "ELECTRONICS", 5999.0, ("STD",))
_WATCH = Product("PRD-ACCESSORIES-D02", "ACCESSORIES", 8999.0, ("BLACK",))


def _plan(order_id: str, account: str, placed: datetime, lines: tuple[Line, ...], method: str, *,
          device: str, address: str, token: str | None, events: list[ScriptedEvent],
          discount: float = 0.0, speed: str = "STANDARD") -> OrderPlan:
    return OrderPlan(account, placed, lines, discount, speed, method, device, address, token,
                     scripted_events=tuple(events), order_id=order_id)


def _delivered(placed: datetime) -> ScriptedEvent:
    return ScriptedEvent("DELIVERED", placed + timedelta(days=3, hours=1))


def _kept(placed: datetime) -> list[ScriptedEvent]:
    return [_delivered(placed)]


def _returned_passed_qc(placed: datetime, fraction: float) -> list[ScriptedEvent]:
    delivered = placed + timedelta(days=3, hours=1)
    requested = delivered + timedelta(days=4)
    qc = requested + timedelta(days=3)
    return [ScriptedEvent("DELIVERED", delivered),
            ScriptedEvent("RETURN_REQUESTED", requested, {"returned_value_fraction": fraction}),
            ScriptedEvent("QC_PASSED", qc, {"evidence_source": "WAREHOUSE_QC"}),
            ScriptedEvent("REFUNDED", qc + timedelta(days=1))]


# ── Demo 1: legitimate frequent returner ─────────────────────────────────────
def _demo_1() -> Population:
    pop = Population()
    pop.accounts.append(AccountSpec(DEMO_1, DEMO_CLOCK - timedelta(days=1280), "DEMO",
                                    source="DEMO", account_id=DEMO_1))
    # 52 weekly orders D3-D360. Of the 48 whose return window has closed by DEMO_CLOCK, 28 are
    # returned (0.58); every return passes QC. The pattern (i*7) % 12 < 7 returns 7 of every 12.
    for i in range(52):
        placed = at(3 + 7 * i, f"{19 + i % 3}:15")
        kind = i % 4
        if kind == 0:
            lines, fraction = (make_line(_DRESS_2, "M"), make_line(_DRESS_2, "L")), 0.5
        elif kind == 1:
            lines, fraction = (make_line(_CANVAS_SHOES, "UK8"),), 1.0
        elif kind == 2:
            lines, fraction = (make_line(_TOP, "M"),), 1.0
        else:
            lines, fraction = (make_line(_BELT, "TAN"),), 1.0
        events = _returned_passed_qc(placed, fraction) if (i * 7) % 12 < 7 else _kept(placed)
        pop.orders.append(_plan(f"ORD-DEMO-001-H{i + 1:02d}", DEMO_1, placed, lines, "PREPAID_UPI",
                                device=D1_DEVICE, address=D1_ADDRESS, token=D1_UPI, events=events,
                                discount=float((i % 3) * 5)))

    # Household member at the same address; last order 73 days before the demo order, so the
    # address link decays to 0.4 * 0.5^(73/45) ~= 0.13 (§11 HOUSEHOLD_PATTERN).
    pop.accounts.append(AccountSpec(DEMO_1_HOUSEHOLD, DEMO_CLOCK - timedelta(days=800), "HOUSEHOLD",
                                    source="DEMO", account_id=DEMO_1_HOUSEHOLD))
    for n, (day, product, variant) in enumerate(
            ((40, _KETTLE, "STD"), (95, _TOP, "M"), (150, _SHOES, "UK8"), (205, _BELT, "TAN"),
             (250, _KETTLE, "STD"), (293, _TOP, "M")), start=1):
        placed = at(day, "10:00")
        events = _returned_passed_qc(placed, 1.0) if day == 150 else _kept(placed)
        pop.orders.append(_plan(f"ORD-DEMO-001-HH{n:02d}", DEMO_1_HOUSEHOLD, placed,
                                (make_line(product, variant),), "PREPAID_UPI",
                                device="DEMO-001-HH:device", address=D1_ADDRESS,
                                token="DEMO-001-HH:upi", events=events))
    return pop


# ── Demo 2: coordinated ring member (context lives in ring R4) ───────────────
def _demo_2() -> Population:
    pop = Population()
    pop.accounts.append(AccountSpec(DEMO_2, DEMO_CLOCK - timedelta(days=6), "DEMO", ring_id="R4",
                                    source="DEMO", account_id=DEMO_2))
    return pop                                  # 0 prior orders


# ── Demo 3: uncertain middle ─────────────────────────────────────────────────
def _demo_3() -> Population:
    pop = Population()
    pop.accounts.append(AccountSpec(DEMO_3, DEMO_CLOCK - timedelta(days=240), "DEMO",
                                    source="DEMO", account_id=DEMO_3))
    own = dict(device=D3_DEVICE, address=D3_ADDRESS)
    t0 = DEMO_PLACED_AT
    history = (
        (130, (make_line(_TOP, "M"),), "COD", _kept),
        (158, (make_line(_SHOES, "UK8"),), "COD", _kept),
        (190, (make_line(_DRESS_2, "M"),), "PREPAID_UPI", lambda p: _returned_passed_qc(p, 1.0)),
        (222, (make_line(_BELT, "TAN"),), "COD", _kept),
        (305, (make_line(_EARPHONES, "STD"),), "COD", _kept),        # CLV ~₹15,000 (§11)
        (350, (make_line(_TOP, "M"),), "PREPAID_UPI", _kept),
    )
    for n, (day, lines, method, outcome) in enumerate(history, start=1):
        placed = at(day, "13:30")
        pop.orders.append(_plan(f"ORD-DEMO-003-H{n:02d}", DEMO_3, placed, lines, method, **own,
                                token=D3_UPI if method != "COD" else None, events=outcome(placed)))
    # Item-not-received claim filed 95 days before the demo order; carrier evidence contradicts
    # it; never adjudicated, so its label is UNRESOLVED.
    claim_at = t0 - timedelta(days=95)
    placed = claim_at - timedelta(days=5)
    pop.orders.append(_plan("ORD-DEMO-003-H07", DEMO_3, placed, (make_line(_EARPHONES, "STD"),),
                            "PREPAID_UPI", **own, token=D3_UPI, events=[
                                ScriptedEvent("DELIVERED", claim_at - timedelta(days=2)),
                                ScriptedEvent("CLAIM_FILED", claim_at, {"claim_type": "ITEM_NOT_RECEIVED"}),
                                ScriptedEvent("CARRIER_EVIDENCE", claim_at + timedelta(days=5),
                                              {"evidence_source": "CARRIER", "contradicts_claim": True}),
                            ]))

    # Device peer: ordering on the same device within the last 30 days, never confirmed.
    pop.accounts.append(AccountSpec(DEMO_3_DEVICE_PEER, at(200, "09:00"), "NORMAL",
                                    source="DEMO", account_id=DEMO_3_DEVICE_PEER))
    for n, day in enumerate((210, 260, 300, 330, 354), start=1):
        placed = at(day, "20:45")
        pop.orders.append(_plan(f"ORD-DEMO-003-DEV{n:02d}", DEMO_3_DEVICE_PEER, placed,
                                (make_line(_BELT if n % 2 else _TOP, "TAN" if n % 2 else "M"),), "PREPAID_UPI",
                                device=D3_DEVICE, address="DEMO-003-DEV:address", token="DEMO-003-DEV:upi",
                                events=_kept(placed)))

    # Address peer: last shipped to Demo 3's address 150 days before the demo order
    # (0.4 * 0.5^(150/45) ~= 0.04, STALE_RELATIONSHIP); that order was confirmed abusive.
    pop.accounts.append(AccountSpec(DEMO_3_ADDRESS_PEER, at(150, "11:00"), "OPPORTUNISTIC",
                                    source="DEMO", account_id=DEMO_3_ADDRESS_PEER))
    placed = at(170, "16:00")
    pop.orders.append(_plan("ORD-DEMO-003-ADR01", DEMO_3_ADDRESS_PEER, placed, (make_line(_KETTLE, "STD"),),
                            "PREPAID_CARD", device="DEMO-003-ADR:device", address=D3_ADDRESS,
                            token="DEMO-003-ADR:card", events=_kept(placed)))
    placed = t0 - timedelta(days=150)
    delivered = placed + timedelta(days=3)
    flagged = delivered + timedelta(days=6)
    pop.orders.append(_plan("ORD-DEMO-003-ADR02", DEMO_3_ADDRESS_PEER, placed, (make_line(_WATCH, "BLACK"),),
                            "PREPAID_CARD", device="DEMO-003-ADR:device", address=D3_ADDRESS,
                            token="DEMO-003-ADR:card", speed="EXPRESS", events=[
                                ScriptedEvent("DELIVERED", delivered),
                                ScriptedEvent("RETURN_REQUESTED", delivered + timedelta(days=3),
                                              {"returned_value_fraction": 1.0}),
                                ScriptedEvent("QC_FLAGGED", flagged,
                                              {"evidence_source": "WAREHOUSE_QC", "finding": "SWAPPED_ITEM"}),
                                ScriptedEvent("ABUSE_CONFIRMED", flagged + timedelta(days=16),
                                              {"evidence_source": "WAREHOUSE_QC"}),
                            ]))
    return pop


def demo_population() -> Population:
    pop = Population()
    for part in (_demo_1(), _demo_2(), _demo_3()):
        pop.extend(part)
    return pop


# ── Demo requests ────────────────────────────────────────────────────────────
def _line_payload(line: Line) -> dict:
    return {"sku_id": line.sku_id, "product_id": line.product_id, "variant": line.variant,
            "category": line.category, "unit_price_inr": line.unit_price_inr, "quantity": line.quantity}


def demo_request_identifiers() -> list[tuple[str, str]]:
    """(kind, value) for every identifier the demo requests use."""
    return [("DEVICE", D1_DEVICE), ("ADDRESS", D1_ADDRESS), ("PAYMENT_TOKEN", D1_UPI),
            ("DEVICE", A.R4_DEVICE_A), ("ADDRESS", D2_ADDRESS), ("PAYMENT_TOKEN", A.R4_TOKEN_T),
            ("DEVICE", D3_DEVICE), ("ADDRESS", D3_ADDRESS)]


def demo_requests(secret: str = HMAC_SECRET) -> list[dict]:
    """ScoreOrderRequest payloads for Demo 1-3 (§11)."""
    from sentinel.features.identifiers import identifier_id

    def ids(device: str, address: str, token: str | None) -> dict:
        return {"device_id": identifier_id("DEVICE", device, secret),
                "address_id": identifier_id("ADDRESS", address, secret),
                "payment_token_id": identifier_id("PAYMENT_TOKEN", token, secret) if token else None}

    dress, phone, sneakers = (ANCHOR_PRODUCTS[k] for k in ("DEMO_DRESS", "R4_PHONE", "DEMO_SNEAKERS"))
    return [
        {"order_id": "ORD-DEMO-001", "account_id": DEMO_1, "placed_at": DEMO_PLACED_AT,
         "lines": [_line_payload(make_line(dress, v)) for v in ("S", "M", "L")],
         "discount_pct": 10.0, "delivery_speed": "STANDARD", "payment_method": "PREPAID_UPI",
         **ids(D1_DEVICE, D1_ADDRESS, D1_UPI)},
        {"order_id": "ORD-DEMO-002", "account_id": DEMO_2, "placed_at": DEMO_PLACED_AT,
         "lines": [_line_payload(make_line(phone, "128GB"))],
         "discount_pct": 0.0, "delivery_speed": "EXPRESS", "payment_method": "PREPAID_CARD",
         **ids(A.R4_DEVICE_A, D2_ADDRESS, A.R4_TOKEN_T)},
        {"order_id": "ORD-DEMO-003", "account_id": DEMO_3, "placed_at": DEMO_PLACED_AT,
         "lines": [_line_payload(make_line(sneakers, "UK9"))],
         "discount_pct": 35.0, "delivery_speed": "STANDARD", "payment_method": "COD",
         **ids(D3_DEVICE, D3_ADDRESS, None)},
    ]
