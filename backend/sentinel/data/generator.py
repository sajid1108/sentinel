"""Seeded synthetic world → event log (§5).

    python -m sentinel.cli generate

Randomness: numpy Generator(PCG64(SeedSequence(20260901))). Every stream (catalog and each
archetype) gets its own child via SeedSequence.spawn, split again into a population child
and an outcome child, so adding an archetype at the end of STREAMS shifts no other stream.

The generator writes world tables and outcome events only. It never writes model features;
features emerge from the events in Phase 3.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sentinel.data import archetypes as A
from sentinel.data import demo_orders, labels as L
from sentinel.features.identifiers import identifier_id
from sentinel.settings import DEMO_CLOCK, HMAC_SECRET

SEED = 20260901

STREAMS = (
    "CATALOG", "NORMAL", "FREQUENT_RETURNER", "HOUSEHOLD", "OFFICE_HOSTEL_PG", "REFURB_DEVICE",
    "OPPORTUNISTIC", "UNCONFIRMED_ABUSER", "RING_R1", "RING_R2", "RING_R3", "RING_R4",
)

ARCHETYPE_GENERATORS = {
    "NORMAL": A.gen_normal,
    "FREQUENT_RETURNER": A.gen_frequent_returner,
    "HOUSEHOLD": A.gen_household,
    "OFFICE_HOSTEL_PG": A.gen_office_hostel_pg,
    "REFURB_DEVICE": A.gen_refurb_device,
    "OPPORTUNISTIC": A.gen_opportunistic,
    "UNCONFIRMED_ABUSER": A.gen_unconfirmed_abuser,
    "RING_R1": lambda rng, cat: A.gen_ring(rng, cat, A.RINGS[0]),
    "RING_R2": lambda rng, cat: A.gen_ring(rng, cat, A.RINGS[1]),
    "RING_R3": lambda rng, cat: A.gen_ring(rng, cat, A.RINGS[2]),
    "RING_R4": A.gen_ring_r4,
}

# Outcome model (§5 "Outcome generation")
CANCEL_PROB = 0.01
COD_RTO_PROB = 0.03
EXCHANGE_SHARE = 0.25
NEVER_RESOLVES_PROB = 0.05          # share of investigated disputes that never resolve
# Investigation coverage (deviation #20). A dispute is evidence-backed when QC flagged the return
# or carrier evidence contradicts the claim; the same coverage applies to every archetype.
EVIDENCE_BACKED_COVERAGE = 0.95
OTHER_DISPUTE_COVERAGE = 0.60
CARRIER_CONTRADICTS_ABUSIVE = 0.95      # tuned for CALIBRATION positives >= 40 (deviation #20)
CARRIER_CONTRADICTS_GENUINE = 0.02
CATEGORY_RETURN_EFFECT = {"APPAREL": 0.35, "FOOTWEAR": 0.25, "ELECTRONICS": -0.35,
                          "BEAUTY": -0.60, "HOME": -0.25, "ACCESSORIES": -0.10}
DISCOUNT_RETURN_EFFECT = 0.012        # per discount point
BRACKETING_RETURN_EFFECT = 0.90
RETURN_NOISE_SD = 0.40

EVENT_TYPES = ("DELIVERED", "RTO", "CANCELLED", "RETURN_REQUESTED", "EXCHANGE_REQUESTED",
               "CLAIM_FILED", "QC_PASSED", "QC_FLAGGED", "CARRIER_EVIDENCE",
               "ABUSE_CONFIRMED", "ABUSE_CLEARED", "REFUNDED")
TYPE_PRIORITY = {"DELIVERED": 0, "RTO": 0, "CANCELLED": 0, "RETURN_REQUESTED": 1,
                 "EXCHANGE_REQUESTED": 1, "CLAIM_FILED": 1, "QC_PASSED": 2, "QC_FLAGGED": 2,
                 "CARRIER_EVIDENCE": 2, "REFUNDED": 3, "ABUSE_CONFIRMED": 4, "ABUSE_CLEARED": 4}

KIND_LABEL = {"DEVICE": "Device", "ADDRESS": "Address", "PAYMENT_TOKEN": "Payment token"}

WORLD_TABLES = ("accounts", "identifiers", "orders", "order_lines", "order_events", "sim_ground_truth")
SORT_KEYS = {
    "accounts": ["account_id"], "identifiers": ["identifier_id"], "orders": ["order_id"],
    "order_lines": ["order_id", "line_no"], "order_events": ["event_id"],
    "sim_ground_truth": ["account_id"], "order_labels": ["order_id"],
}
# §5 "Generator outputs"; one Parquet file per table (deviation #17)
OUTPUT_FILES = {
    "accounts": "accounts.parquet", "identifiers": "identifiers.parquet", "orders": "orders.parquet",
    "order_lines": "order_lines.parquet", "order_events": "events.parquet",
    "sim_ground_truth": "sim_ground_truth.parquet", "order_labels": "labels.parquet",
}


# ── Ids ──────────────────────────────────────────────────────────────────────
def _hmac_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def display_label(kind: str, ident: str) -> str:
    return f"{KIND_LABEL[kind]} ••{ident[-4:]}"


def _account_id(key: str, secret: str) -> str:
    return "ACC-" + _hmac_hex(secret, f"ACCOUNT:{key}")[:10].upper()


def _order_id(key: str, seq: int, secret: str) -> str:
    return "ORD-" + _hmac_hex(secret, f"ORDER:{key}:{seq}")[:12].upper()


# ── Randomness ───────────────────────────────────────────────────────────────
def stream_generators(seed: int = SEED) -> dict[str, tuple[np.random.Generator, np.random.Generator]]:
    root = np.random.SeedSequence(seed)
    streams = {}
    for name, child in zip(STREAMS, root.spawn(len(STREAMS))):
        population, outcomes = child.spawn(2)
        streams[name] = (np.random.Generator(np.random.PCG64(population)),
                         np.random.Generator(np.random.PCG64(outcomes)))
    return streams


# ── Outcomes ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Event:
    event_type: str
    occurred_at: datetime
    attributes: dict


def _after(ts: datetime, days: float) -> datetime:
    return ts + timedelta(seconds=int(round(days * 86400)))


def return_probability(plan: A.OrderPlan, rng: np.random.Generator) -> float:
    """§5: p = f(archetype, category, discount, bracketing) + noise."""
    b = plan.behaviour
    z = (b.return_logit + CATEGORY_RETURN_EFFECT[plan.primary_category]
         + DISCOUNT_RETURN_EFFECT * plan.discount_pct
         + (BRACKETING_RETURN_EFFECT if plan.n_variants_same_product >= 2 else 0.0)
         + rng.normal(0.0, RETURN_NOISE_SD))
    return 1.0 / (1.0 + math.exp(-z))


def returned_value_fraction(plan: A.OrderPlan, rng: np.random.Generator) -> float:
    values = [ln.unit_price_inr * ln.quantity for ln in plan.lines]
    total = sum(values)
    if plan.n_variants_same_product >= 2:          # size bracketing: keep one size, return the rest
        by_product: dict[str, list[int]] = {}
        for i, ln in enumerate(plan.lines):
            by_product.setdefault(ln.product_id, []).append(i)
        bracket = max(by_product.values(), key=len)
        keep = bracket[int(rng.integers(len(bracket)))]
        returned = sum(values[i] for i in bracket if i != keep)
    elif len(plan.lines) > 1 and rng.random() < 0.5:
        returned = values[int(rng.integers(len(values)))]
    else:
        returned = total
    return round(returned / total, 4)


def simulate_outcomes(plan: A.OrderPlan, rng: np.random.Generator) -> list[Event]:
    b = plan.behaviour
    placed = plan.placed_at
    if rng.random() < CANCEL_PROB:
        return [Event("CANCELLED", _after(placed, rng.uniform(0.02, 0.5)), {})]
    if plan.payment_method == "COD" and rng.random() < COD_RTO_PROB:
        return [Event("RTO", _after(placed, rng.uniform(2, 7)), {})]
    delivered = _after(placed, rng.uniform(2, 7))
    events = [Event("DELIVERED", delivered, {})]
    if b.keep:
        return events

    abusive = b.abuse_mode is not None
    dispute_at, evidence, source = None, False, None
    if b.abuse_mode == "CLAIM" or (not abusive and rng.random() < b.genuine_claim_prob):
        claim_type = A.pick(rng, ("EMPTY_BOX", "ITEM_NOT_RECEIVED")) if abusive else "ITEM_NOT_RECEIVED"
        claim_at = _after(delivered, rng.uniform(0.1, 5))
        carrier_at = _after(claim_at, rng.uniform(3, 10))
        contradicts = bool(rng.random() < (CARRIER_CONTRADICTS_ABUSIVE if abusive else CARRIER_CONTRADICTS_GENUINE))
        events.append(Event("CLAIM_FILED", claim_at, {"claim_type": claim_type}))
        events.append(Event("CARRIER_EVIDENCE", carrier_at,
                            {"evidence_source": "CARRIER", "contradicts_claim": contradicts}))
        dispute_at, evidence, source = carrier_at, contradicts, "CARRIER"
    else:
        p = 1.0 if abusive else return_probability(plan, rng)
        if rng.random() < p:
            requested = _after(delivered, rng.uniform(1, 30))
            exchange = (not abusive and plan.primary_category in A.SIZED and rng.random() < EXCHANGE_SHARE)
            fraction = 1.0 if abusive else returned_value_fraction(plan, rng)
            events.append(Event("EXCHANGE_REQUESTED" if exchange else "RETURN_REQUESTED", requested,
                                {"returned_value_fraction": fraction}))
            qc_at = _after(requested, rng.uniform(2, 6))
            flag_prob = b.qc_flag_prob_abusive if abusive else b.qc_flag_prob_genuine
            if rng.random() < flag_prob:
                finding = A.pick(rng, ("EMPTY_BOX", "SWAPPED_ITEM", "USED_ITEM", "TAGS_REMOVED") if abusive
                                 else ("USED_ITEM", "TAGS_REMOVED"))
                events.append(Event("QC_FLAGGED", qc_at, {"evidence_source": "WAREHOUSE_QC", "finding": finding}))
                dispute_at, evidence, source = qc_at, True, "WAREHOUSE_QC"
            else:
                events.append(Event("QC_PASSED", qc_at, {"evidence_source": "WAREHOUSE_QC"}))
                if not exchange:
                    events.append(Event("REFUNDED", _after(qc_at, rng.uniform(0.5, 2)), {}))

    if dispute_at is not None:
        coverage = (EVIDENCE_BACKED_COVERAGE if evidence else OTHER_DISPUTE_COVERAGE) if b.investigated else 0.0
        if rng.random() < coverage:
            if rng.random() >= NEVER_RESOLVES_PROB:
                resolved = _after(dispute_at, rng.uniform(3, 25))
                if abusive and evidence:
                    events.append(Event("ABUSE_CONFIRMED", resolved, {"evidence_source": source}))
                else:
                    events.append(Event("ABUSE_CLEARED", resolved, {"evidence_source": "ADJUDICATION"}))
                    if source == "CARRIER":
                        events.append(Event("REFUNDED", _after(resolved, rng.uniform(0.5, 2)), {}))
        elif source == "CARRIER":               # claims nobody investigates are paid out
            events.append(Event("REFUNDED", _after(dispute_at, rng.uniform(1, 3)), {}))
    return events


# ── World assembly ───────────────────────────────────────────────────────────
@dataclass
class World:
    tables: dict[str, pd.DataFrame]     # WORLD_TABLES + "order_labels"

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self.tables[name]


def _utc(values) -> pd.Series:
    return pd.Series(pd.to_datetime(list(values), utc=True)).astype("datetime64[us, UTC]")


def _json(attrs: dict) -> str:
    return json.dumps(attrs, sort_keys=True, separators=(",", ":"))


def generate(seed: int = SEED, secret: str = HMAC_SECRET) -> World:
    streams = stream_generators(seed)
    catalog = A.build_catalog(streams["CATALOG"][0])

    account_rows, truth_rows = [], []
    order_rows, line_rows, event_rows = [], [], []
    identifiers: dict[str, tuple[str, str]] = {}          # id -> (kind, value)
    multi_tenant: dict[str, datetime] = {}
    key_to_id: dict[str, str] = {}
    acc_archetype: dict[str, str] = {}

    def register(kind: str, value: str) -> str:
        ident = identifier_id(kind, value, secret)
        seen = identifiers.setdefault(ident, (kind, value))
        if seen != (kind, value):
            raise ValueError(f"identifier id collision: {seen} vs {(kind, value)}")
        return ident

    populations = [(name, gen(streams[name][0], catalog), streams[name][1])
                   for name, gen in ARCHETYPE_GENERATORS.items()]
    populations.append(("DEMO", demo_orders.demo_population(), None))

    for name, pop, outcome_rng in populations:
        for acc in pop.accounts:
            account_id = acc.account_id or _account_id(acc.key, secret)
            if acc.key in key_to_id:
                raise ValueError(f"duplicate account key {acc.key}")
            key_to_id[acc.key] = account_id
            acc_archetype[acc.key] = acc.archetype
            account_rows.append((account_id, acc.created_at, acc.source))
            truth_rows.append((account_id, acc.archetype, acc.ring_id))
        for address, set_at in pop.multi_tenant_addresses.items():
            multi_tenant[identifier_id("ADDRESS", address, secret)] = set_at
        seq: dict[str, int] = {}
        for plan in pop.orders:
            n = seq.get(plan.account_key, 0)
            seq[plan.account_key] = n + 1
            order_id = plan.order_id or _order_id(plan.account_key, n, secret)
            day = A.day_of(plan.placed_at)
            value = round(sum(ln.unit_price_inr * ln.quantity for ln in plan.lines)
                          * (1 - plan.discount_pct / 100), 2)
            order_rows.append((
                order_id, key_to_id[plan.account_key], plan.placed_at, value, plan.discount_pct,
                sum(ln.quantity for ln in plan.lines), plan.n_variants_same_product, plan.primary_category,
                plan.delivery_speed, plan.payment_method, register("DEVICE", plan.device),
                register("ADDRESS", plan.address),
                register("PAYMENT_TOKEN", plan.token) if plan.token is not None else None,
                "HISTORY", "RECENT" if acc_archetype[plan.account_key] == "DEMO"
                else A.split_for_day(day),
            ))
            for i, ln in enumerate(plan.lines, start=1):
                line_rows.append((order_id, i, ln.sku_id, ln.product_id, ln.variant, ln.category,
                                  ln.unit_price_inr, ln.quantity))
            if plan.scripted_events is not None:
                events = [Event(e.event_type, e.occurred_at, e.attributes) for e in plan.scripted_events]
            else:
                events = simulate_outcomes(plan, outcome_rng)
            for e in events:
                if e.occurred_at < A.HORIZON:
                    event_rows.append((order_id, e.event_type, e.occurred_at, _json(e.attributes)))

    for kind, value in demo_orders.demo_request_identifiers():
        register(kind, value)

    accounts = pd.DataFrame(account_rows, columns=["account_id", "created_at", "source"])
    accounts["created_at"] = _utc(accounts["created_at"])

    ident_ids = sorted(identifiers)
    identifiers_df = pd.DataFrame({
        "identifier_id": ident_ids,
        "kind": [identifiers[i][0] for i in ident_ids],
        "is_multi_tenant": [int(i in multi_tenant) for i in ident_ids],
        "multi_tenant_set_at": _utc([multi_tenant.get(i) for i in ident_ids]),
        "display_label": [display_label(identifiers[i][0], i) for i in ident_ids],
    })

    orders = pd.DataFrame(order_rows, columns=[
        "order_id", "account_id", "placed_at", "order_value_inr", "discount_pct", "n_items",
        "n_variants_same_product", "primary_category", "delivery_speed", "payment_method",
        "device_id", "address_id", "payment_token_id", "source", "split"])
    orders["placed_at"] = _utc(orders["placed_at"])
    orders = orders.sort_values(["placed_at", "order_id"], kind="stable").reset_index(drop=True)

    order_lines = pd.DataFrame(line_rows, columns=[
        "order_id", "line_no", "sku_id", "product_id", "variant", "category", "unit_price_inr", "quantity"])
    order_lines = order_lines.sort_values(["order_id", "line_no"], kind="stable").reset_index(drop=True)

    events_df = pd.DataFrame(event_rows, columns=["order_id", "event_type", "occurred_at", "attributes_json"])
    events_df["occurred_at"] = _utc(events_df["occurred_at"])
    events_df["_priority"] = events_df["event_type"].map(TYPE_PRIORITY)
    events_df = (events_df.sort_values(["occurred_at", "_priority", "order_id"], kind="stable")
                 .drop(columns="_priority").reset_index(drop=True))
    events_df.insert(0, "event_id", np.arange(1, len(events_df) + 1, dtype="int64"))

    truth = pd.DataFrame(truth_rows, columns=["account_id", "archetype", "ring_id"])
    truth = truth.sort_values("account_id", kind="stable").reset_index(drop=True)
    accounts = accounts.sort_values("account_id", kind="stable").reset_index(drop=True)

    world = World({
        "accounts": accounts, "identifiers": identifiers_df, "orders": orders,
        "order_lines": order_lines, "order_events": events_df, "sim_ground_truth": truth,
    })
    _validate(world)
    world.tables["order_labels"] = L.derive_labels(orders["order_id"], events_df, as_of=A.HORIZON)
    return world


def _validate(world: World) -> None:
    accounts, orders, events = world["accounts"], world["orders"], world["order_events"]
    for name, key in (("accounts", "account_id"), ("orders", "order_id"), ("identifiers", "identifier_id")):
        if world[name][key].duplicated().any():
            raise ValueError(f"duplicate {key} in {name}")
    created = orders["account_id"].map(accounts.set_index("account_id")["created_at"])
    if created.isna().any() or (orders["placed_at"] <= created).any():
        raise ValueError("every order needs an account created before it")
    days = (orders["placed_at"] - pd.Timestamp(A.SIM_START)) // pd.Timedelta(days=1) + 1
    if not days.between(1, A.LAST_ORDER_DAY).all():
        raise ValueError("orders must be placed D1-D365")
    placed = events["order_id"].map(orders.set_index("order_id")["placed_at"])
    if placed.isna().any() or (events["occurred_at"] <= placed).any():
        raise ValueError("every event must follow its order's placement")
    if ((orders["payment_method"] == "COD") != orders["payment_token_id"].isna()).any():
        raise ValueError("payment_token_id must be null exactly for COD")


# ── Views, hashing, outputs ──────────────────────────────────────────────────
def as_of_view(world: World, clock: datetime = DEMO_CLOCK) -> dict[str, pd.DataFrame]:
    """The world as the live system may see it: nothing at or after `clock` (§5, P12).

    Ground truth and labels are offline-only and are not part of the view.
    """
    ts = pd.Timestamp(clock)
    accounts = world["accounts"][world["accounts"]["created_at"] < ts]
    orders = world["orders"][world["orders"]["placed_at"] < ts]
    events = world["order_events"][world["order_events"]["occurred_at"] < ts]
    lines = world["order_lines"][world["order_lines"]["order_id"].isin(orders["order_id"])]
    identifiers = world["identifiers"].copy()
    future_flag = identifiers["multi_tenant_set_at"].notna() & (identifiers["multi_tenant_set_at"] >= ts)
    identifiers.loc[future_flag, "is_multi_tenant"] = 0
    identifiers.loc[future_flag, "multi_tenant_set_at"] = pd.NaT
    return {"accounts": accounts.reset_index(drop=True), "identifiers": identifiers,
            "orders": orders.reset_index(drop=True), "order_lines": lines.reset_index(drop=True),
            "order_events": events.reset_index(drop=True)}


def event_log_sha256(world: World) -> str:
    """SHA-256 over every world table, each sorted by its key and serialised canonically."""
    h = hashlib.sha256()
    for name in WORLD_TABLES:
        df = world[name].sort_values(SORT_KEYS[name], kind="stable").reset_index(drop=True)
        h.update(name.encode("utf-8"))
        h.update(df.to_csv(index=False, lineterminator="\n", date_format="%Y-%m-%dT%H:%M:%S%z").encode("utf-8"))
    return h.hexdigest()


def write_outputs(world: World, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, filename in OUTPUT_FILES.items():
        path = out_dir / filename
        world[name].to_parquet(path, index=False)
        paths[name] = path
    return paths


def summarize(world: World) -> dict[str, float | int | str]:
    orders, lab, truth = world["orders"], world["order_labels"], world["sim_ground_truth"]
    merged = orders[["order_id", "split"]].merge(lab, on="order_id")
    return {
        "accounts": len(world["accounts"]),
        "orders": len(orders),
        "events": len(world["order_events"]),
        "return_rate": float(lab["return_label"].dropna().mean()),
        "confirmed_abuse_rate": float((lab["abuse_status"] == "CONFIRMED").mean()),
        "unresolved": int((lab["abuse_status"] == "UNRESOLVED").sum()),
        "test_abuse_positives": int(((merged["split"] == "TEST") & (merged["abuse_label"] == 1)).sum()),
        "rings": int(truth["ring_id"].dropna().nunique()),
        "sha256": event_log_sha256(world),
    }


FLAGGED_CLAIM_EVENTS = ("CLAIM_FILED", "QC_FLAGGED")


def ring_order_account_history(world: World) -> pd.DataFrame:
    """Ring (R1-R4) orders with the member's own history at placement (offline diagnostics).

    prior_orders: the member's orders placed before this one. own_flagged_180d: CLAIM_FILED or
    QC_FLAGGED events on the member's own orders in [placed_at - 180 d, placed_at).
    """
    orders, truth, ev = world["orders"], world["sim_ground_truth"], world["order_events"]
    ring = orders.merge(truth[truth["archetype"] == "RING"], on="account_id")
    flags = ev[ev["event_type"].isin(FLAGGED_CLAIM_EVENTS)].merge(orders[["order_id", "account_id"]], on="order_id")
    def utc_micros(ts: pd.Series) -> np.ndarray:
        return ts.dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[us]").to_numpy()

    flag_times = {a: np.sort(utc_micros(g["occurred_at"])) for a, g in flags.groupby("account_id")}
    order_times = {a: np.sort(utc_micros(g["placed_at"])) for a, g in orders.groupby("account_id")}
    window = np.timedelta64(180, "D")
    prior, own = [], []
    for account, t in zip(ring["account_id"], utc_micros(ring["placed_at"])):
        prior.append(int(np.searchsorted(order_times[account], t, side="left")))
        times = flag_times.get(account)
        own.append(0 if times is None else int(np.searchsorted(times, t, side="left")
                                               - np.searchsorted(times, t - window, side="left")))
    return ring.assign(prior_orders=prior, own_flagged_180d=own)


def world_stats(world: World) -> dict:
    """Figures printed by `python -m sentinel.cli world-stats` (offline only)."""
    orders, lab, ev = world["orders"], world["order_labels"], world["order_events"]
    merged = orders[["order_id", "split"]].merge(lab, on="order_id")
    disputed = set(ev.loc[ev["event_type"].isin(FLAGGED_CLAIM_EVENTS), "order_id"])
    unresolved = int((lab["abuse_status"] == "UNRESOLVED").sum())
    positives = (merged[merged["abuse_label"] == 1].groupby("split").size()
                 .reindex(["TRAIN", "GAP", "CALIBRATION", "TEST", "RECENT"], fill_value=0))
    ring = ring_order_account_history(world)
    per_member = ring.groupby(["ring_id", "account_id"]).size()
    rings = {rid: {"members": int(len(g)), "median_orders": float(g.median()), "max_orders": int(g.max())}
             for rid, g in per_member.groupby(level="ring_id")}
    return {
        "accounts": len(world["accounts"]),
        "orders": len(orders),
        "return_rate": float(lab["return_label"].dropna().mean()),
        "confirmed_abuse_share": float((lab["abuse_status"] == "CONFIRMED").mean()),
        "disputed_orders": len(disputed),
        "unresolved": unresolved,
        "unresolved_share_of_disputes": unresolved / len(disputed) if disputed else 0.0,
        "positives_by_split": {k: int(v) for k, v in positives.items()},
        "rings": rings,
        "ring_orders_with_own_prior_flagged_claim": float((ring["own_flagged_180d"] >= 1).mean()),
    }
