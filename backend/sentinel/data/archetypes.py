"""Synthetic-world archetypes (§5).

Each archetype generator returns a Population: accounts, order plans and, for multi-tenant
sites, the time the address was flagged. A plan holds order-time facts only (cart, payment,
identifiers) plus the hidden Behaviour that drives outcome sampling in generator.py, or a
hand-authored list of scripted events. Nothing here computes a model feature.

Identifiers are synthetic values (for example "NORMAL-0001:device:0"); generator.py turns
them into HMAC ids. Values never leave the generator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence, TypeVar

import numpy as np

from sentinel.settings import IST

T = TypeVar("T")

# ── Timeline (§5) ────────────────────────────────────────────────────────────
SIM_START = datetime(2025, 9, 1, tzinfo=IST)          # D1 00:00 IST
DAY = timedelta(days=1)
LAST_ORDER_DAY = 365
HORIZON = SIM_START + 440 * DAY                        # end of D440: outcomes simulated to here


def day_start(day: int) -> datetime:
    return SIM_START + (day - 1) * DAY


def day_of(ts: datetime) -> int:
    return (ts - SIM_START) // DAY + 1


def at(day: int, hhmm: str) -> datetime:
    hh, mm = hhmm.split(":")
    return day_start(day) + timedelta(hours=int(hh), minutes=int(mm))


def split_for_day(day: int) -> str:
    if day <= 200:
        return "TRAIN"
    if day <= 230:
        return "GAP"
    if day <= 275:
        return "CALIBRATION"
    if day <= 305:
        return "GAP"
    if day <= 365:
        return "TEST"
    return "RECENT"


# ── Catalog ──────────────────────────────────────────────────────────────────
CATEGORIES = ("APPAREL", "FOOTWEAR", "ELECTRONICS", "BEAUTY", "HOME", "ACCESSORIES")
SIZED = frozenset({"APPAREL", "FOOTWEAR"})
PRICE_RANGES = {
    "APPAREL": (399, 4999), "FOOTWEAR": (799, 9999), "ELECTRONICS": (999, 79999),
    "BEAUTY": (199, 2999), "HOME": (299, 14999), "ACCESSORIES": (299, 24999),
}
VARIANTS = {
    "APPAREL": ("XS", "S", "M", "L", "XL"), "FOOTWEAR": ("UK6", "UK7", "UK8", "UK9", "UK10"),
    "ELECTRONICS": ("64GB", "128GB", "256GB"), "BEAUTY": ("STD",), "HOME": ("STD",),
    "ACCESSORIES": ("BLACK", "BROWN", "TAN"),
}
PRODUCTS_PER_CATEGORY = 30


@dataclass(frozen=True)
class Product:
    product_id: str
    category: str
    price_inr: float
    variants: tuple[str, ...]


# Fixed products used by hand-authored histories (§11). Never drawn at random.
ANCHOR_PRODUCTS = {
    "DEMO_DRESS": Product("PRD-APPAREL-D01", "APPAREL", 1666.67, ("S", "M", "L")),
    "DEMO_SNEAKERS": Product("PRD-FOOTWEAR-D01", "FOOTWEAR", 18461.54, ("UK8", "UK9")),
    "R4_PHONE": Product("PRD-ELECTRONICS-R01", "ELECTRONICS", 24000.0, ("128GB",)),
    "R4_EARBUDS": Product("PRD-ELECTRONICS-R02", "ELECTRONICS", 4999.0, ("STD",)),
}


@dataclass(frozen=True)
class Line:
    sku_id: str
    product_id: str
    variant: str
    category: str
    unit_price_inr: float
    quantity: int


def make_line(product: Product, variant: str, quantity: int = 1) -> Line:
    return Line(f"SKU-{product.product_id[4:]}-{variant}", product.product_id, variant,
                product.category, product.price_inr, quantity)


@dataclass(frozen=True)
class Catalog:
    products: dict[str, tuple[Product, ...]]          # per category, sorted by price

    def band(self, category: str, band: str | None) -> tuple[Product, ...]:
        items = self.products[category]
        third = len(items) // 3
        if band == "LOW":
            return items[:third]
        if band == "HIGH":
            return items[-third:]
        return items


def build_catalog(rng: np.random.Generator) -> Catalog:
    products = {}
    for category in CATEGORIES:
        lo, hi = PRICE_RANGES[category]
        items = []
        for i in range(PRODUCTS_PER_CATEGORY):
            price = math.exp(rng.uniform(math.log(lo), math.log(hi)))
            price = max(lo, round(price / 100) * 100 - 1)
            items.append(Product(f"PRD-{category}-{i + 1:03d}", category, float(price), VARIANTS[category]))
        products[category] = tuple(sorted(items, key=lambda p: (p.price_inr, p.product_id)))
    return Catalog(products)


# ── Plans ────────────────────────────────────────────────────────────────────
GENUINE_COVERAGE = 0.60          # investigation coverage for disputes on genuine accounts
OPPORTUNISTIC_COVERAGE = 0.50    # §5
RING_COVERAGE = 0.70             # §5
QC_FLAG_ABUSIVE = 0.75           # §5
QC_FLAG_GENUINE = 0.02           # §5
GENUINE_CLAIM_PROB = 0.005       # §5: lost parcels


@dataclass(frozen=True)
class Behaviour:
    """Hidden truth for outcome sampling. Never written to any output table."""
    return_logit: float
    abuse_mode: str | None = None            # None | "RETURN" | "CLAIM"
    investigation_coverage: float = GENUINE_COVERAGE
    qc_flag_prob_abusive: float = QC_FLAG_ABUSIVE
    qc_flag_prob_genuine: float = QC_FLAG_GENUINE
    genuine_claim_prob: float = GENUINE_CLAIM_PROB
    keep: bool = False                       # ring cover order: kept, no claim


@dataclass(frozen=True)
class ScriptedEvent:
    event_type: str
    occurred_at: datetime
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AccountSpec:
    key: str
    created_at: datetime
    archetype: str
    ring_id: str | None = None
    source: str = "SYNTHETIC"
    account_id: str | None = None            # fixed id for hand-authored accounts


@dataclass(frozen=True)
class OrderPlan:
    account_key: str
    placed_at: datetime
    lines: tuple[Line, ...]
    discount_pct: float
    delivery_speed: str
    payment_method: str
    device: str
    address: str
    token: str | None
    behaviour: Behaviour | None = None
    scripted_events: tuple[ScriptedEvent, ...] | None = None
    order_id: str | None = None              # fixed id for hand-authored orders

    @property
    def primary_category(self) -> str:
        value: dict[str, float] = {}
        for ln in self.lines:
            value[ln.category] = value.get(ln.category, 0.0) + ln.unit_price_inr * ln.quantity
        return max(sorted(value), key=lambda c: value[c])

    @property
    def n_variants_same_product(self) -> int:
        variants: dict[str, set[str]] = {}
        for ln in self.lines:
            variants.setdefault(ln.product_id, set()).add(ln.variant)
        return max(len(v) for v in variants.values())


@dataclass
class Population:
    accounts: list[AccountSpec] = field(default_factory=list)
    orders: list[OrderPlan] = field(default_factory=list)
    multi_tenant_addresses: dict[str, datetime] = field(default_factory=dict)

    def extend(self, other: "Population") -> None:
        self.accounts.extend(other.accounts)
        self.orders.extend(other.orders)
        self.multi_tenant_addresses.update(other.multi_tenant_addresses)


# ── Sampling helpers ─────────────────────────────────────────────────────────
def pick(rng: np.random.Generator, options: Sequence[T], weights: Sequence[float] | None = None) -> T:
    if weights is None:
        return options[int(rng.integers(len(options)))]
    w = np.asarray(weights, dtype=float)
    return options[int(rng.choice(len(options), p=w / w.sum()))]


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def time_on_day(rng: np.random.Generator, day: int) -> datetime:
    """Orders are placed between 08:00 and 24:00 IST, to the second."""
    return day_start(day) + timedelta(seconds=int(rng.integers(8 * 3600, 24 * 3600)))


def before(rng: np.random.Generator, ts: datetime, min_days: float, max_days: float) -> datetime:
    return ts - timedelta(seconds=int(rng.uniform(min_days, max_days) * 86400))


def order_days(rng: np.random.Generator, first: int, last: int, annual_rate: float,
               min_orders: int = 1) -> list[int]:
    span = last - first + 1
    n = max(min_orders, int(rng.poisson(annual_rate * span / 365)))
    return sorted(int(d) for d in rng.integers(first, last + 1, size=n))


def annual_rate(rng: np.random.Generator, median: float, sigma: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, math.exp(rng.normal(math.log(median), sigma)))))


def draw_discount(rng: np.random.Generator, deep_prob: float = 0.10) -> float:
    u = rng.random()
    if u < 0.45:
        return 0.0
    if u < 1.0 - deep_prob:
        return float(rng.integers(5, 21))
    return float(rng.integers(25, 61))


@dataclass(frozen=True)
class Profile:
    category_weights: tuple[float, ...]      # aligned with CATEGORIES
    bracket_prob: float
    payment_weights: tuple[float, float, float]   # PREPAID_CARD, PREPAID_UPI, COD
    express_prob: float
    price_band: str | None = None
    extra_item_prob: float = 0.25
    deep_discount_prob: float = 0.10


PAYMENT_METHODS = ("PREPAID_CARD", "PREPAID_UPI", "COD")

NORMAL_PROFILE = Profile((0.28, 0.12, 0.15, 0.17, 0.16, 0.12), 0.06, (0.25, 0.45, 0.30), 0.15)
RETURNER_PROFILE = Profile((0.50, 0.25, 0.05, 0.05, 0.05, 0.10), 0.50, (0.40, 0.50, 0.10), 0.20)
STUDENT_PROFILE = Profile((0.35, 0.15, 0.25, 0.15, 0.05, 0.05), 0.05, (0.10, 0.45, 0.45), 0.10)
HIGH_VALUE_PROFILE = Profile((0.0, 0.0, 0.6, 0.0, 0.0, 0.4), 0.0, (0.30, 0.35, 0.35), 0.40,
                             price_band="HIGH", extra_item_prob=0.05)
COVER_PROFILE = Profile((0.4, 0.0, 0.0, 0.3, 0.3, 0.0), 0.0, (0.0, 0.6, 0.4), 0.10,
                        price_band="LOW", extra_item_prob=0.0, deep_discount_prob=0.0)


def build_cart(rng: np.random.Generator, catalog: Catalog, profile: Profile) -> tuple[Line, ...]:
    category = pick(rng, CATEGORIES, profile.category_weights)
    product = pick(rng, catalog.band(category, profile.price_band))
    lines: list[Line] = []
    if category in SIZED and rng.random() < profile.bracket_prob:
        k = int(rng.integers(2, 5))
        idx = sorted(int(i) for i in rng.choice(len(product.variants), size=k, replace=False))
        lines.extend(make_line(product, product.variants[i]) for i in idx)
    else:
        qty = 2 if category in ("BEAUTY", "HOME") and rng.random() < 0.10 else 1
        lines.append(make_line(product, pick(rng, product.variants), qty))
    if rng.random() < profile.extra_item_prob:
        other_cat = pick(rng, CATEGORIES)
        other = pick(rng, catalog.band(other_cat, "LOW"))
        if other.product_id != product.product_id:
            lines.append(make_line(other, pick(rng, other.variants)))
    return tuple(lines)


@dataclass(frozen=True)
class Wallet:
    """An account's own identifiers."""
    device: str
    address: str
    upi: str
    card: str

    @staticmethod
    def own(key: str) -> "Wallet":
        return Wallet(f"{key}:device:0", f"{key}:address:0", f"{key}:upi:0", f"{key}:card:0")


def token_for(method: str, upi: str, card: str) -> str | None:
    return {"PREPAID_UPI": upi, "PREPAID_CARD": card, "COD": None}[method]


def sampled_order(rng: np.random.Generator, catalog: Catalog, key: str, placed_at: datetime,
                  profile: Profile, behaviour: Behaviour, *, device: str, address: str,
                  upi: str, card: str, lines: tuple[Line, ...] | None = None,
                  method: str | None = None) -> OrderPlan:
    lines = lines if lines is not None else build_cart(rng, catalog, profile)
    discount = draw_discount(rng, profile.deep_discount_prob)
    speed = "EXPRESS" if rng.random() < profile.express_prob else "STANDARD"
    method = method or pick(rng, PAYMENT_METHODS, profile.payment_weights)
    return OrderPlan(key, placed_at, lines, discount, speed, method, device, address,
                     token_for(method, upi, card), behaviour=behaviour)


def genuine(return_rate: float, **kwargs) -> Behaviour:
    return Behaviour(return_logit=logit(return_rate), **kwargs)


def created_before(rng: np.random.Generator, first_day: int, min_days: float, max_days: float) -> datetime:
    """Account creation strictly before any order on first_day (orders start at 08:00)."""
    return before(rng, day_start(first_day), min_days, max_days)


# ── NORMAL ───────────────────────────────────────────────────────────────────
NORMAL_ACCOUNTS = 2090           # + 60 refurbished-device prior owners ≈ 2,150 NORMAL


def gen_normal(rng: np.random.Generator, catalog: Catalog) -> Population:
    pop = Population()
    for i in range(NORMAL_ACCOUNTS):
        key = f"NORMAL-{i:04d}"
        if rng.random() < 0.65:
            first = 1
            created = created_before(rng, 1, 30, 2000)
        else:
            first = int(rng.integers(1, 351))
            created = day_start(first) + timedelta(seconds=int(rng.integers(0, 8 * 3600)))
        last = 365 if rng.random() > 0.20 else int(rng.integers(min(first + 30, 365), 366))
        days = order_days(rng, first, last, annual_rate(rng, 3.0, 0.7, 1, 15))
        w = Wallet.own(key)
        second_device_day = int(rng.integers(first, 366)) if rng.random() < 0.15 else None
        second_address = rng.random() < 0.10
        behaviour = genuine(float(rng.uniform(0.04, 0.20)))
        pop.accounts.append(AccountSpec(key, created, "NORMAL"))
        for d in days:
            device = f"{key}:device:1" if second_device_day and d >= second_device_day else w.device
            address = f"{key}:address:1" if second_address and rng.random() < 0.3 else w.address
            pop.orders.append(sampled_order(rng, catalog, key, time_on_day(rng, d), NORMAL_PROFILE,
                                            behaviour, device=device, address=address,
                                            upi=w.upi, card=w.card))
    return pop


# ── FREQUENT_RETURNER ────────────────────────────────────────────────────────
FREQUENT_RETURNER_ACCOUNTS = 250


def gen_frequent_returner(rng: np.random.Generator, catalog: Catalog) -> Population:
    pop = Population()
    for i in range(FREQUENT_RETURNER_ACCOUNTS):
        key = f"FREQRET-{i:04d}"
        created = created_before(rng, 1, 400, 2500)             # tenure > 1 year
        days = order_days(rng, 1, 365, float(rng.uniform(4, 9)), min_orders=3)
        w = Wallet.own(key)
        # "QC always passes" (§5)
        behaviour = genuine(float(rng.uniform(0.30, 0.55)), qc_flag_prob_genuine=0.0)
        pop.accounts.append(AccountSpec(key, created, "FREQUENT_RETURNER"))
        for d in days:
            pop.orders.append(sampled_order(rng, catalog, key, time_on_day(rng, d), RETURNER_PROFILE,
                                            behaviour, device=w.device, address=w.address,
                                            upi=w.upi, card=w.card))
    return pop


# ── HOUSEHOLD (hard negative) ────────────────────────────────────────────────
HOUSEHOLDS = 40


def gen_household(rng: np.random.Generator, catalog: Catalog) -> Population:
    pop = Population()
    for h in range(HOUSEHOLDS):
        hkey = f"HOUSEHOLD-{h:02d}"
        address = f"{hkey}:address"
        shared_card = f"{hkey}:card" if rng.random() < 0.50 else None      # §5: 50 % share a card
        family_device = f"{hkey}:device" if rng.random() < 0.25 else None   # shared family tablet
        for m in range(int(rng.integers(2, 5))):
            key = f"{hkey}-M{m}"
            if rng.random() < 0.6:
                first, created = 1, created_before(rng, 1, 30, 1500)
            else:
                first = int(rng.integers(1, 300))
                created = day_start(first) + timedelta(seconds=int(rng.integers(0, 8 * 3600)))
            days = order_days(rng, first, 365, annual_rate(rng, 4.0, 0.5, 2, 12))
            w = Wallet.own(key)
            behaviour = genuine(float(rng.uniform(0.05, 0.22)))
            pop.accounts.append(AccountSpec(key, created, "HOUSEHOLD"))
            for d in days:
                card = shared_card if shared_card and rng.random() < 0.8 else w.card
                device = family_device if family_device and rng.random() < 0.35 else w.device
                addr = address if rng.random() < 0.95 else w.address
                pop.orders.append(sampled_order(rng, catalog, key, time_on_day(rng, d), NORMAL_PROFILE,
                                                behaviour, device=device, address=addr,
                                                upi=w.upi, card=card))
    return pop


# ── OFFICE / HOSTEL / PG (hard negative) ─────────────────────────────────────
MULTI_TENANT_SITES = ("OFFICE", "HOSTEL", "PG")
MULTI_TENANT_FLAG_AFTER_ACCOUNTS = 8


def gen_office_hostel_pg(rng: np.random.Generator, catalog: Catalog) -> Population:
    pop = Population()
    for site in MULTI_TENANT_SITES:
        address = f"SITE-{site}:address"
        n = int(rng.integers(25, 61))
        cohort1_devices: list[str] = []
        for m in range(n):
            key = f"SITE-{site}-{m:03d}"
            w = Wallet.own(key)
            device = w.device
            profile = NORMAL_PROFILE
            to_site = 0.70
            if site == "OFFICE":
                first, last = 1, 365
                created = created_before(rng, 1, 60, 1800)
            elif site == "HOSTEL":
                profile, to_site = STUDENT_PROFILE, 0.90
                if m < n // 2:                     # senior cohort leaves after D170
                    first, last = 1, 170
                    created = created_before(rng, 1, 30, 700)
                    cohort1_devices.append(device)
                else:                              # junior cohort arrives from D240
                    first, last = 240, 365
                    created = created_before(rng, 240, 0.2, 20)
                    if cohort1_devices and rng.random() < 0.35:
                        # handed-down phone: previous owner inactive on it for >= 70 days
                        device = cohort1_devices.pop(int(rng.integers(len(cohort1_devices))))
            else:
                first = int(rng.integers(1, 250))
                last = int(rng.integers(first + 60, 366))
                to_site = 0.90
                created = created_before(rng, first, 0.2, 400)
            days = order_days(rng, first, last, annual_rate(rng, 4.0, 0.6, 1, 14))
            behaviour = genuine(float(rng.uniform(0.05, 0.22)))
            pop.accounts.append(AccountSpec(key, created, "OFFICE_HOSTEL_PG"))
            for d in days:
                addr = address if rng.random() < to_site else w.address
                pop.orders.append(sampled_order(rng, catalog, key, time_on_day(rng, d), profile,
                                                behaviour, device=device, address=addr,
                                                upi=w.upi, card=w.card))
        firsts: dict[str, datetime] = {}
        for o in pop.orders:
            if o.address == address:
                firsts[o.account_key] = min(o.placed_at, firsts.get(o.account_key, o.placed_at))
        nth = sorted(firsts.values())[MULTI_TENANT_FLAG_AFTER_ACCOUNTS - 1]
        pop.multi_tenant_addresses[address] = nth + timedelta(seconds=int(rng.uniform(1, 14) * 86400))
    return pop


# ── REFURB_DEVICE (hard negative) ────────────────────────────────────────────
REFURB_ACCOUNTS = 60


def gen_refurb_device(rng: np.random.Generator, catalog: Catalog) -> Population:
    pop = Population()
    for i in range(REFURB_ACCOUNTS):
        owner, buyer = f"REFURB-OWNER-{i:02d}", f"REFURB-{i:02d}"
        device = f"{owner}:device:0"
        last_owner_day = int(rng.integers(20, 201))
        start = min(350, last_owner_day + int(rng.integers(90, 151)))
        # prior owner: a NORMAL customer who stops ordering after last_owner_day
        ow = Wallet.own(owner)
        n_owner = int(rng.integers(2, 7))
        owner_days = sorted(int(d) for d in rng.integers(max(1, last_owner_day - 150), last_owner_day, size=n_owner - 1))
        owner_days.append(last_owner_day)
        pop.accounts.append(AccountSpec(owner, created_before(rng, owner_days[0], 30, 1500), "NORMAL"))
        owner_behaviour = genuine(float(rng.uniform(0.04, 0.20)))
        for d in owner_days:
            pop.orders.append(sampled_order(rng, catalog, owner, time_on_day(rng, d), NORMAL_PROFILE,
                                            owner_behaviour, device=device, address=ow.address,
                                            upi=ow.upi, card=ow.card))
        bw = Wallet.own(buyer)
        behaviour = genuine(float(rng.uniform(0.04, 0.20)))
        buyer_days: list[int] = []
        if rng.random() < 0.40 and start > 10:     # existing customer switching phones
            created = created_before(rng, 1, 30, 1500)
            for d in sorted(int(x) for x in rng.integers(1, start - 5, size=int(rng.integers(1, 4)))):
                pop.orders.append(sampled_order(rng, catalog, buyer, time_on_day(rng, d), NORMAL_PROFILE,
                                                behaviour, device=f"{buyer}:device:old",
                                                address=bw.address, upi=bw.upi, card=bw.card))
        else:                                      # new account on a second-hand phone
            created = created_before(rng, start, 0.1, 5)
        buyer_days = [start] + order_days(rng, start, 365, annual_rate(rng, 3.5, 0.6, 1, 12))
        pop.accounts.append(AccountSpec(buyer, created, "REFURB_DEVICE"))
        for d in buyer_days:
            pop.orders.append(sampled_order(rng, catalog, buyer, time_on_day(rng, d), NORMAL_PROFILE,
                                            behaviour, device=device, address=bw.address,
                                            upi=bw.upi, card=bw.card))
    return pop


# ── OPPORTUNISTIC and UNCONFIRMED_ABUSER ─────────────────────────────────────
OPPORTUNISTIC_ACCOUNTS = 90
UNCONFIRMED_ABUSER_ACCOUNTS = 30


def _gen_opportunistic(rng: np.random.Generator, catalog: Catalog, n_accounts: int,
                       archetype: str, prefix: str) -> Population:
    unconfirmed = archetype == "UNCONFIRMED_ABUSER"
    coverage = 0.0 if unconfirmed else OPPORTUNISTIC_COVERAGE
    pop = Population()
    for i in range(n_accounts):
        key = f"{prefix}-{i:03d}"
        w = Wallet.own(key)
        b0 = int(rng.integers(5, 346))
        if rng.random() < 0.60:                                  # new account
            created = created_before(rng, b0, 0.2, 20)
        else:                                                    # dormant account
            created = created_before(rng, 1, 200, 1500)
            if b0 > 150 and rng.random() < 0.5:
                old = genuine(0.15, investigation_coverage=coverage)
                for d in sorted(int(x) for x in rng.integers(1, b0 - 120, size=int(rng.integers(1, 3)))):
                    pop.orders.append(sampled_order(rng, catalog, key, time_on_day(rng, d), NORMAL_PROFILE,
                                                    old, device=w.device, address=w.address,
                                                    upi=w.upi, card=w.card))
        pop.accounts.append(AccountSpec(key, created, archetype))
        n = int(rng.integers(2, 6))
        end = min(365, b0 + int(rng.integers(10, 61)))
        days = [b0] + sorted(int(x) for x in rng.integers(b0, end + 1, size=n - 1))
        abusive = set(int(x) for x in rng.choice(n, size=min(n, int(rng.integers(1, 3))), replace=False))
        burst_device = f"{key}:device:burst" if rng.random() < 0.40 else w.device   # sometimes a new device
        return_rate = float(rng.uniform(0.40, 0.65))
        for j, d in enumerate(days):
            if j in abusive:
                mode = "RETURN" if unconfirmed or rng.random() < 0.5 else "CLAIM"
                behaviour = Behaviour(return_logit=logit(return_rate), abuse_mode=mode,
                                      investigation_coverage=coverage,
                                      # undetected wardrobing: QC passes, so the account stays labelled 0
                                      qc_flag_prob_abusive=QC_FLAG_GENUINE if unconfirmed else QC_FLAG_ABUSIVE)
                profile = HIGH_VALUE_PROFILE
            else:
                behaviour = genuine(return_rate, investigation_coverage=coverage)
                profile = HIGH_VALUE_PROFILE if rng.random() < 0.5 else NORMAL_PROFILE
            pop.orders.append(sampled_order(rng, catalog, key, time_on_day(rng, d), profile, behaviour,
                                            device=burst_device, address=w.address,
                                            upi=w.upi, card=w.card))
    return pop


def gen_opportunistic(rng: np.random.Generator, catalog: Catalog) -> Population:
    return _gen_opportunistic(rng, catalog, OPPORTUNISTIC_ACCOUNTS, "OPPORTUNISTIC", "OPPORT")


def gen_unconfirmed_abuser(rng: np.random.Generator, catalog: Catalog) -> Population:
    return _gen_opportunistic(rng, catalog, UNCONFIRMED_ABUSER_ACCOUNTS, "UNCONFIRMED_ABUSER", "UNCONF")


# ── RINGS ────────────────────────────────────────────────────────────────────
RING_COVER_SHARE = 0.20
RING_SHARED_DEVICE_PROB = 0.85
RING_SHARED_TOKEN_PROB = 0.75
RING_PAYMENT_WEIGHTS = (0.60, 0.25, 0.15)
RING_ADDRESSES_PER_MEMBER = 4


def ring_address(rng: np.random.Generator, member_key: str) -> str:
    return f"{member_key}:drop-address:{int(rng.integers(RING_ADDRESSES_PER_MEMBER))}"


@dataclass(frozen=True)
class RingSpec:
    ring_id: str
    members: int
    start_day: int
    end_day: int
    n_devices: int
    n_tokens: int
    orders_per_member_day: float
    earliest_day: int = 1            # no account or order of the ring before this day


RINGS = (
    RingSpec("R1", 8, 40, 90, 2, 1, 0.45),
    RingSpec("R2", 12, 170, 260, 3, 2, 0.40),
    RingSpec("R3", 10, 315, 345, 2, 1, 0.60, earliest_day=306),   # cold-start ring: TEST only
)


def _ring_abusive_order(rng, catalog, key, placed_at, targets, *, device, token,
                        own_card, own_upi, address, product: Product | None = None) -> OrderPlan:
    if product is None:
        product = pick(rng, targets) if rng.random() < 0.70 else pick(
            rng, catalog.band(pick(rng, ("ELECTRONICS", "ACCESSORIES")), "HIGH"))
    lines = (make_line(product, pick(rng, product.variants)),)
    behaviour = Behaviour(return_logit=logit(0.3),
                          abuse_mode="CLAIM" if rng.random() < 0.6 else "RETURN",
                          investigation_coverage=RING_COVERAGE)
    discount = float(rng.integers(0, 16)) if rng.random() < 0.5 else 0.0
    speed = "EXPRESS" if rng.random() < 0.5 else "STANDARD"
    method = pick(rng, PAYMENT_METHODS, RING_PAYMENT_WEIGHTS)
    card = token if token is not None and method == "PREPAID_CARD" else own_card
    return OrderPlan(key, placed_at, lines, discount, speed, method, device, address,
                     token_for(method, own_upi, card), behaviour=behaviour)


def _ring_cover_order(rng, catalog, key, placed_at, *, device, address, w: Wallet) -> OrderPlan:
    return sampled_order(rng, catalog, key, placed_at, COVER_PROFILE,
                         genuine(0.05, keep=True, investigation_coverage=RING_COVERAGE),
                         device=device, address=address, upi=w.upi, card=w.card)


def _ring_prior_orders(rng, catalog, key, days, w: Wallet) -> list[OrderPlan]:
    b = genuine(0.12, investigation_coverage=RING_COVERAGE)
    return [sampled_order(rng, catalog, key, time_on_day(rng, d), NORMAL_PROFILE, b,
                          device=w.device, address=w.address, upi=w.upi, card=w.card) for d in days]


def _ring_targets(rng, catalog) -> tuple[Product, ...]:
    return (pick(rng, catalog.band("ELECTRONICS", "HIGH")), pick(rng, catalog.band("ACCESSORIES", "HIGH")))


def gen_ring(rng: np.random.Generator, catalog: Catalog, spec: RingSpec) -> Population:
    pop = Population()
    rid = spec.ring_id
    devices = [f"RING-{rid}:device:{j}" for j in range(spec.n_devices)]
    tokens = [f"RING-{rid}:card:{j}" for j in range(spec.n_tokens)]
    # Addresses rotate deliberately: each member cycles through its own drop addresses, so an
    # address never links two members. Device and token carry the ring signal (§5).
    targets = _ring_targets(rng, catalog)
    window = spec.end_day - spec.start_day + 1
    bursts = sorted(int(d) for d in rng.choice(np.arange(spec.start_day, spec.end_day + 1),
                                               size=max(3, window // 3), replace=False))
    earliest = day_start(spec.earliest_day)
    for m in range(spec.members):
        key = f"RING-{rid}-{m:02d}"
        w = Wallet.own(key)
        n_prior = int(rng.integers(0, 4))                     # 0–3 prior orders
        lo = max(spec.earliest_day, spec.start_day - 90)
        prior_days = sorted(int(d) for d in rng.integers(lo, spec.start_day - 2, size=n_prior))
        first_day = prior_days[0] if prior_days else spec.start_day
        created = created_before(rng, first_day, 0.2, 30)
        if spec.earliest_day > 1:
            created = max(earliest, created)
        pop.accounts.append(AccountSpec(key, created, "RING", ring_id=rid))
        pop.orders.extend(_ring_prior_orders(rng, catalog, key, prior_days, w))
        shared_device, shared_token = devices[m % len(devices)], tokens[m % len(tokens)]
        n = max(3, int(rng.poisson(spec.orders_per_member_day * window)))
        for _ in range(n):
            placed_at = time_on_day(rng, pick(rng, bursts))
            device = shared_device if rng.random() < RING_SHARED_DEVICE_PROB else w.device
            address = ring_address(rng, key)
            if rng.random() < RING_COVER_SHARE:
                pop.orders.append(_ring_cover_order(rng, catalog, key, placed_at, device=device,
                                                    address=address, w=w))
            else:
                token = shared_token if rng.random() < RING_SHARED_TOKEN_PROB else None
                pop.orders.append(_ring_abusive_order(rng, catalog, key, placed_at, targets,
                                                      device=device, token=token, own_card=w.card,
                                                      own_upi=w.upi, address=address))
    return pop


# ── RING R4: hand-scheduled so Demo 2's context is exact (§11) ───────────────
R4_MEMBERS = 7
R4_DEVICE_A = "RING-R4:device:A"       # members 1-5, and the Demo 2 order
R4_DEVICE_B = "RING-R4:device:B"       # members 6-7
R4_TOKEN_T = "RING-R4:card:T"          # members 4-6, and the Demo 2 order

# (member, placed day, time, confirmation day, time): abusive returns flagged by QC and
# confirmed D356-D362. These are the only R4 confirmations before DEMO_CLOCK.
R4_CONFIRMED = (
    (1, 340, "13:10", 356, "15:00"),
    (2, 342, "12:25", 359, "12:00"),
    (3, 344, "18:40", 362, "16:30"),
)
# (member, day, time, device, token, anchor product or None). Every order is placed on or
# after D359, so no outcome of these orders can resolve before DEMO_CLOCK (min chain 8 days).
R4_SCHEDULE = (
    (1, 360, "12:40", "A", "own", None), (1, 363, "19:05", "A", "own", None),
    (2, 361, "15:20", "A", "own", None),
    (3, 362, "20:10", "A", "own", None), (3, 364, "13:35", "A", "own", None),
    (4, 359, "18:45", "A", "T", None), (4, 362, "11:30", "A", "T", None),
    (5, 360, "21:00", "A", "T", None), (5, 363, "16:15", "A", "own", None),
    (6, 361, "14:50", "B", "T", None), (6, 364, "10:05", "B", "T", None),
    (7, 360, "17:25", "B", "own", None),
    # the 24 hours before the Demo 2 order: 4 linked orders, 3 of them the Demo 2 phone
    (4, 365, "11:40", "A", "T", "R4_PHONE"), (5, 365, "14:05", "A", "T", "R4_PHONE"),
    (6, 365, "18:30", "B", "T", "R4_PHONE"), (7, 365, "21:15", "B", "own", "R4_EARBUDS"),
)


def r4_key(member: int) -> str:
    return f"RING-R4-{member:02d}"


def gen_ring_r4(rng: np.random.Generator, catalog: Catalog) -> Population:
    pop = Population()
    targets = (ANCHOR_PRODUCTS["R4_PHONE"], ANCHOR_PRODUCTS["R4_EARBUDS"])
    wallets = {m: Wallet.own(r4_key(m)) for m in range(1, R4_MEMBERS + 1)}
    first_activity = {m: min([d for mm, d, *_ in R4_CONFIRMED if mm == m]
                             + [d for mm, d, *_ in R4_SCHEDULE if mm == m]) for m in wallets}
    for m, w in wallets.items():
        key = r4_key(m)
        n_prior = int(rng.integers(0, 2)) if m <= 3 else int(rng.integers(0, 4))
        prior_days = sorted(int(d) for d in rng.integers(250, 336, size=n_prior))
        first_day = prior_days[0] if prior_days else first_activity[m]
        pop.accounts.append(AccountSpec(key, created_before(rng, first_day, 0.2, 30), "RING", ring_id="R4"))
        pop.orders.extend(_ring_prior_orders(rng, catalog, key, prior_days, w))

    phone = ANCHOR_PRODUCTS["R4_PHONE"]
    for m, day, hhmm, confirm_day, confirm_hhmm in R4_CONFIRMED:
        w, placed = wallets[m], at(day, hhmm)
        delivered = placed + timedelta(days=3, hours=2)
        requested = delivered + timedelta(days=2, hours=5)
        flagged = requested + timedelta(days=3, hours=1)
        events = (
            ScriptedEvent("DELIVERED", delivered),
            ScriptedEvent("RETURN_REQUESTED", requested, {"returned_value_fraction": 1.0}),
            ScriptedEvent("QC_FLAGGED", flagged, {"evidence_source": "WAREHOUSE_QC", "finding": "SWAPPED_ITEM"}),
            ScriptedEvent("ABUSE_CONFIRMED", at(confirm_day, confirm_hhmm), {"evidence_source": "WAREHOUSE_QC"}),
        )
        pop.orders.append(OrderPlan(r4_key(m), placed, (make_line(phone, "128GB"),), 0.0, "EXPRESS",
                                    "PREPAID_CARD", R4_DEVICE_A, ring_address(rng, r4_key(m)), w.card,
                                    scripted_events=events))

    for m, day, hhmm, dev, tok, product_name in R4_SCHEDULE:
        w, key, placed = wallets[m], r4_key(m), at(day, hhmm)
        device = R4_DEVICE_A if dev == "A" else R4_DEVICE_B
        address = ring_address(rng, key)
        if product_name is None and rng.random() < RING_COVER_SHARE:
            pop.orders.append(_ring_cover_order(rng, catalog, key, placed, device=device, address=address, w=w))
            continue
        plan = _ring_abusive_order(rng, catalog, key, placed, targets, device=device, token=None,
                                   own_card=w.card, own_upi=w.upi, address=address,
                                   product=ANCHOR_PRODUCTS[product_name] if product_name else None)
        card = R4_TOKEN_T if tok == "T" else w.card
        pop.orders.append(OrderPlan(plan.account_key, plan.placed_at, plan.lines, plan.discount_pct,
                                    plan.delivery_speed, "PREPAID_CARD", plan.device, plan.address,
                                    card, behaviour=plan.behaviour))
    return pop
