"""A tiny hand-built world for point-in-time feature tests."""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from sentinel.api.schemas import ScoreOrderRequest
from sentinel.features.builder import FeatureBuilder
from sentinel.features.identifiers import identifier_id
from sentinel.settings import DEMO_CLOCK

T0 = DEMO_CLOCK - timedelta(days=10)
DAY = timedelta(days=1)


def _utc(values) -> pd.Series:
    return pd.Series(pd.to_datetime(list(values), utc=True)).astype("datetime64[us, UTC]")


class MiniWorld:
    def __init__(self):
        self.accounts: dict[str, object] = {}
        self.idents: dict[str, tuple[str, object]] = {}
        self.orders: list[dict] = []
        self.lines: list[tuple] = []
        self.events: list[tuple] = []
        self.skus: dict[str, str] = {}

    def ident(self, kind: str, value: str, multi_tenant_set_at=None) -> str:
        ident = identifier_id(kind, value)
        self.idents[ident] = (kind, multi_tenant_set_at)
        return ident

    def raw_ident(self, kind: str, ident: str) -> str:
        """Register an already-hashed id as-is (used for placeholder ids)."""
        self.idents[ident] = (kind, None)
        return ident

    def account(self, account_id: str, created=None) -> str:
        self.accounts[account_id] = created if created is not None else T0 - 400 * DAY
        return account_id

    def order(self, order_id: str, account_id: str, placed_at, *, device: str | None = None,
              address: str | None = None, token: str | None = "own", sku: str = "SKU-A",
              price: float = 1000.0, category: str = "APPAREL") -> dict:
        if account_id not in self.accounts:
            self.account(account_id)
        device = device or self.ident("DEVICE", f"{account_id}:device")
        address = address or self.ident("ADDRESS", f"{account_id}:address")
        if token == "own":
            token = self.ident("PAYMENT_TOKEN", f"{account_id}:token")
        row = {"order_id": order_id, "account_id": account_id, "placed_at": placed_at, "order_value_inr": price,
               "discount_pct": 0.0, "n_items": 1, "n_variants_same_product": 1, "primary_category": category,
               "delivery_speed": "STANDARD", "payment_method": "COD" if token is None else "PREPAID_CARD",
               "device_id": device, "address_id": address, "payment_token_id": token, "source": "HISTORY",
               "split": "TRAIN"}
        self.orders.append(row)
        self.lines.append((order_id, 1, sku, f"PRD-{sku}", "M", category, price, 1))
        self.skus[order_id] = sku
        return row

    def event(self, order_id: str, event_type: str, occurred_at, **attrs) -> None:
        self.events.append((order_id, event_type, occurred_at, json.dumps(attrs)))

    def tables(self) -> dict[str, pd.DataFrame]:
        accounts = pd.DataFrame({"account_id": list(self.accounts), "created_at": _utc(self.accounts.values()),
                                 "source": "SYNTHETIC"})
        ids = sorted(self.idents)
        identifiers = pd.DataFrame({
            "identifier_id": ids, "kind": [self.idents[i][0] for i in ids],
            "is_multi_tenant": [int(self.idents[i][1] is not None) for i in ids],
            "multi_tenant_set_at": _utc([self.idents[i][1] for i in ids]),
            "display_label": [f"{self.idents[i][0].title()} ••{i[-4:]}" for i in ids]})
        orders = pd.DataFrame(self.orders)
        orders["placed_at"] = _utc(orders["placed_at"])
        lines = pd.DataFrame(self.lines, columns=["order_id", "line_no", "sku_id", "product_id", "variant", "category",
                                                  "unit_price_inr", "quantity"])
        events = pd.DataFrame(self.events, columns=["order_id", "event_type", "occurred_at", "attributes_json"])
        events["occurred_at"] = _utc(events["occurred_at"])
        events = events.sort_values("occurred_at", kind="stable").reset_index(drop=True)
        events.insert(0, "event_id", range(1, len(events) + 1))
        return {"accounts": accounts, "identifiers": identifiers, "orders": orders, "order_lines": lines,
                "order_events": events}

    def request(self, row: dict) -> ScoreOrderRequest:
        return ScoreOrderRequest(
            order_id=row["order_id"], account_id=row["account_id"], placed_at=row["placed_at"],
            lines=[{"sku_id": self.skus[row["order_id"]], "product_id": f"PRD-{self.skus[row['order_id']]}",
                    "variant": "M", "category": row["primary_category"],
                    "unit_price_inr": row["order_value_inr"], "quantity": 1}],
            discount_pct=0, delivery_speed="STANDARD", payment_method=row["payment_method"],
            device_id=row["device_id"], address_id=row["address_id"], payment_token_id=row["payment_token_id"])


def features_at(world: MiniWorld, row: dict) -> dict:
    """Serving path: replay to the order's placed_at, then features_for_request."""
    builder = FeatureBuilder.replay(world.tables(), row["placed_at"])
    return builder.features_for_request(world.request(row))


def builder_at(world: MiniWorld, t0) -> FeatureBuilder:
    return FeatureBuilder.replay(world.tables(), t0)


def offline_features(world: MiniWorld) -> dict[str, dict]:
    return {r.order_id: r.features for r in FeatureBuilder(world.tables()).iter_order_features()}
