"""Record the landing page's "Try an order" grid from the real API (brief: docs/briefs/landing-try-an-order.md).

The live landing page is static, so it can only replay answers. This script seeds a fresh database in a
temporary folder (the real backend/data/sentinel.db is never opened), serves it with the real app over local
HTTP, and places every combination of the grid through the public checkout once, then reads the recorded
decision from GET /internal/orders/{id}, as the Phase 10 panel does. Nothing is scored twice.

The grid:
- accounts, device options, token options and categories: GET /internal/demo/order-builder
- payment methods: the ScoreOrderRequest enum in frontend/src/api/openapi.json
- the cart otherwise follows the first preset (quantity, number of sizes, discount, delivery), built the way
  frontend/src/lib/tryOrder.ts buildRequest builds it; the order value takes two bands, the lowest and the
  highest preset order value. The first preset's own order is therefore in the grid and is the default.
- COD carries no token, so a COD combination has token "-". OWN is left out for an account with no device
  (token) of its own, as the form disables it.

A NEW device or token is a fresh id from a fresh builder call for every combination, never a reused one.

At the end, ORDER_CHECK_SAMPLE combinations are placed again with new order ids and compared with the first
pass. The shopper's support reference is a digest of the decision id, which is new for every order by design,
so it is masked in that comparison; every other value must match exactly or the script fails.

Usage (from the repo root): backend/.venv/Scripts/python scripts/record_try_grid.py
Writes landing/try-grid.json.
"""
from __future__ import annotations

import json
import random
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sentinel.api.main import create_app                    # noqa: E402
from sentinel.db.seed import seed_database                  # noqa: E402
from sentinel.settings import INTERNAL_API_KEY              # noqa: E402

OUT = ROOT / "landing" / "try-grid.json"
OPENAPI = ROOT / "frontend" / "src" / "api" / "openapi.json"
SIZES = ["S", "M", "L", "XL"]                               # tryOrder.ts SIZES
TOP_REASONS = 4
ORDER_CHECK_SAMPLE = 20
MAX_BYTES = 3 * 1024 * 1024
NO_TOKEN = "-"


# ── local API ────────────────────────────────────────────────────────────────
class Api:
    def __init__(self, base: str) -> None:
        self.base = base

    def call(self, method: str, path: str, body: dict | None = None, internal: bool = False) -> dict:
        headers = {"Content-Type": "application/json"}
        if internal:
            headers["X-Internal-Key"] = INTERNAL_API_KEY
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc

    def builder(self) -> dict:
        return self.call("GET", "/api/v1/internal/demo/order-builder", internal=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(db_path: Path):
    import uvicorn
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(db_path, demo_mode=True), host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread, Api(f"http://127.0.0.1:{port}")


# ── grid ─────────────────────────────────────────────────────────────────────
def order_value(preset: dict) -> float:
    return sum(ln["unit_price_inr"] * ln["quantity"] for ln in preset["lines"]) * (1 - preset["discount_pct"] / 100)


def define_grid(builder: dict, presets: list[dict], payments: list[str]) -> dict:
    first = presets[0]
    products = {ln["product_id"] for ln in first["lines"]}
    quantities = {ln["quantity"] for ln in first["lines"]}
    if len(products) != 1 or len(quantities) != 1 or len(first["lines"]) > len(SIZES):
        raise SystemExit("the first preset is not a one-product cart the form can build")
    cart = {"quantity": first["lines"][0]["quantity"], "sizes": len(first["lines"]),
            "discount_pct": first["discount_pct"], "delivery_speed": first["delivery_speed"]}
    values = sorted({order_value(p) for p in presets})
    bands = [values[0], values[-1]]
    divisor = cart["sizes"] * cart["quantity"] * (1 - cart["discount_pct"] / 100)
    unit_prices = [round(v / divisor, 2) for v in bands]
    default_band = bands.index(order_value(first)) if order_value(first) in bands else None
    if default_band is None or unit_prices[default_band] != first["lines"][0]["unit_price_inr"]:
        raise SystemExit("the first preset's own cart is not in the grid")
    own = builder["accounts"]
    return {
        "cart": cart, "unit_prices": unit_prices, "categories": builder["categories"], "payments": payments,
        "accounts": [a["account_id"] for a in own],
        "devices": [d["option"] for d in builder["devices"]], "tokens": [t["option"] for t in builder["tokens"]],
        "default": key(first["account_id"], first["lines"][0]["category"], default_band, first["payment_method"],
                       "OWN", NO_TOKEN if first["payment_method"] == "COD" else "OWN"),
    }


def key(account: str, category: str, band: int, payment: str, device: str, token: str) -> str:
    return f"{account}|{category}|{band}|{payment}|{device}|{token}"


def combinations(grid: dict, builder: dict) -> list[tuple]:
    """Every combination the Phase 10 form can place. It disables OWN for an account with no device (token)
    of its own, so those combinations are not in the grid."""
    out = []
    for account in builder["accounts"]:
        devices = [d for d in grid["devices"] if d != "OWN" or account["device_id"] is not None]
        tokens = [t for t in grid["tokens"] if t != "OWN" or account["payment_token_id"] is not None]
        for category in grid["categories"]:
            for band in range(len(grid["unit_prices"])):
                for payment in grid["payments"]:
                    for device in devices:
                        for token in ([NO_TOKEN] if payment == "COD" else tokens):
                            out.append((account["account_id"], category, band, payment, device, token))
    return out


def resolve(choice: str, options: list[dict], own: str | None) -> str | None:
    if choice == "OWN":
        return own
    return next(o["identifier_id"] for o in options if o["option"] == choice)


def build_request(combo: tuple, grid: dict, builder: dict) -> dict:
    """tryOrder.ts buildRequest, with the grid's cart."""
    account_id, category, band, payment, device, token = combo
    account = next(a for a in builder["accounts"] if a["account_id"] == account_id)
    device_id = resolve(device, builder["devices"], account["device_id"])
    token_id = None if payment == "COD" else resolve(token, builder["tokens"], account["payment_token_id"])
    if device_id is None or (payment != "COD" and token_id is None):
        raise SystemExit(f"{combo}: the account has no identifier of its own")
    cart = grid["cart"]
    return {
        "order_id": "ORD-TRY-" + secrets.token_hex(4).upper(),
        "account_id": account_id,
        "placed_at": builder["placed_at"],
        "lines": [{"sku_id": f"SKU-TRY-{category}-{i + 1}", "product_id": f"PRD-TRY-{category}", "variant": size,
                   "category": category, "unit_price_inr": grid["unit_prices"][band], "quantity": cart["quantity"]}
                  for i, size in enumerate(SIZES[:cart["sizes"]])],
        "discount_pct": cart["discount_pct"],
        "delivery_speed": cart["delivery_speed"],
        "payment_method": payment,
        "device_id": device_id,
        "address_id": account["address_id"],
        "payment_token_id": token_id,
    }


# ── one combination ──────────────────────────────────────────────────────────
def place(api: Api, combo: tuple, grid: dict, builder: dict) -> dict:
    """Checkout once, then read the decision. Returns the full record (the file keeps a compact form)."""
    if "NEW" in (combo[4], combo[5]):
        builder = api.builder()                                # a fresh NEW id for this combination
    outcome = api.call("POST", "/api/v1/public/checkout/decision", build_request(combo, grid, builder))
    detail = api.call("GET", f"/api/v1/internal/orders/{outcome['order_id']}", internal=True)
    decision = detail["decision"]
    if decision["degraded_mode"] or decision["idempotent_replay"]:
        raise SystemExit(f"{combo}: degraded or replayed decision")
    policy, scores = decision["policy"], decision["scores"]
    return {
        "outcome": outcome["outcome"],
        "message": outcome["customer_message"],
        "reference": outcome["support_reference"],
        "value": detail["order"]["order_value"]["display"],
        "action": detail["current_action"],
        "cost_optimal": policy["cost_optimal_action"],
        "p_abuse": scores["p_abuse"],
        "p_return": scores["p_return"],
        "p_abuse_without_graph": scores["p_abuse_without_graph_evidence"],
        "signals": [s["signal"] for s in decision["graph_summary"]["signals"] if s["counts_for_corroboration"]],
        "costs": [[c["action"], c["expected_cost"]["display"], c["excluded_by"]] for c in policy["costs"]],
        "reasons": [[r["code"], r["reviewer_text"]] for r in decision["reasons"][:TOP_REASONS]],
        "explanation": policy["policy_explanation"],
        "policy_version": policy["policy_version"],
        "versions": [scores["return_model_version"], scores["abuse_model_version"], scores["feature_set_version"]],
    }


def comparable(record: dict) -> dict:
    """Everything except the per-decision support reference (masked where the message carries it)."""
    out = {k: v for k, v in record.items() if k != "reference"}
    out["message"] = record["message"].replace(record["reference"], "<ref>")
    return out


# ── compact file ─────────────────────────────────────────────────────────────
FIELDS = ["outcome", "message", "action", "cost_optimal", "p_abuse", "p_return", "p_abuse_without_graph",
          "signals", "costs", "reasons", "explanation"]


def compact(records: dict[str, dict], grid: dict, builder: dict, presets: list[dict], meta: dict) -> dict:
    strings: list[str] = []
    index: dict[str, int] = {}

    def s(text: str) -> int:
        if text not in index:
            index[text] = len(strings)
            strings.append(text)
        return index[text]

    results = {}
    for k, r in records.items():
        results[k] = [r["outcome"], s(r["message"]), r["action"], r["cost_optimal"], r["p_abuse"], r["p_return"],
                      r["p_abuse_without_graph"], r["signals"], r["costs"],
                      [[code, s(text)] for code, text in r["reasons"]], s(r["explanation"])]
    band_values = []
    for band in range(len(grid["unit_prices"])):
        shown = {r["value"] for k, r in records.items() if k.split("|")[2] == str(band)}
        if len(shown) != 1:
            raise SystemExit(f"band {band} shows {shown}")
        band_values.append(shown.pop())
    return {
        **meta,
        "fields": FIELDS,
        "notes": {"strings": "message, reasons[i][1] and explanation are indexes into strings",
                  "key": "account|category|value band|payment method|device|token"},
        "cart": {**grid["cart"], "unit_price_inr": grid["unit_prices"], "value_display": band_values},
        "accounts": [{k: a[k] for k in ("account_id", "label", "account_age_days", "prior_orders")}
                     for a in builder["accounts"]],
        "categories": grid["categories"], "payments": grid["payments"],
        "devices": grid["devices"], "tokens": grid["tokens"],
        "presets": [p["order_id"] for p in presets],
        "default": grid["default"],
        "strings": strings,
        "results": results,
    }


def git_sha() -> tuple[str, bool]:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    return sha.stdout.strip(), bool(dirty.stdout.strip())


def main() -> None:
    started = time.perf_counter()
    workdir = Path(tempfile.mkdtemp(prefix="try-grid-"))
    try:
        db_path = workdir / "sentinel.db"
        print(f"seeding a fresh database in {workdir} ...", flush=True)
        seed_database(db_path=db_path)
        presets = json.loads((workdir / "demo_presets.json").read_text(encoding="utf-8"))
        payments = json.loads(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"][
            "ScoreOrderRequest"]["properties"]["payment_method"]["enum"]
        server, thread, api = serve(db_path)
        try:
            builder = api.builder()
            grid = define_grid(builder, presets, payments)
            combos = combinations(grid, builder)
            print(f"grid: {len(combos)} combinations; default {grid['default']}", flush=True)
            records: dict[str, dict] = {}
            for i, combo in enumerate(combos, 1):
                records[key(*combo)] = place(api, combo, grid, builder)
                if i % 100 == 0 or i == len(combos):
                    print(f"  {i}/{len(combos)}  {time.perf_counter() - started:.0f} s", flush=True)

            versions = {tuple(r["versions"]) for r in records.values()}
            policies = {r["policy_version"] for r in records.values()}
            if len(versions) != 1 or len(policies) != 1:
                raise SystemExit(f"versions changed during the run: {versions} {policies}")

            rng = random.Random()
            sample = rng.sample(combos, ORDER_CHECK_SAMPLE)
            mismatches = []
            for combo in sample:
                again = place(api, combo, grid, builder)
                if comparable(again) != comparable(records[key(*combo)]):
                    mismatches.append((key(*combo), comparable(records[key(*combo)]), comparable(again)))
            if mismatches:
                for k, first, second in mismatches:
                    print(f"MISMATCH {k}\n  first  {first}\n  second {second}")
                raise SystemExit(f"order independence failed on {len(mismatches)} of {ORDER_CHECK_SAMPLE}")
            print(f"order independence: {ORDER_CHECK_SAMPLE} of {ORDER_CHECK_SAMPLE} re-scored combinations match",
                  flush=True)
        finally:
            server.should_exit = True
            thread.join(timeout=30)

        sha, dirty = git_sha()
        (return_v, abuse_v, fs_v), = versions
        meta = {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_sha": sha,
                "git_dirty": dirty, "policy_version": policies.pop(), "return_model_version": return_v,
                "abuse_model_version": abuse_v, "feature_set_version": fs_v, "placed_at": builder["placed_at"],
                "order_check": {"sample": ORDER_CHECK_SAMPLE, "matched": ORDER_CHECK_SAMPLE,
                                "keys": sorted(key(*c) for c in sample)}}
        body = compact(records, grid, builder, presets, meta)
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"
        size = len(text.encode("utf-8"))
        if size >= MAX_BYTES:
            raise SystemExit(f"try-grid.json would be {size} bytes (limit {MAX_BYTES})")
        OUT.write_text(text, encoding="utf-8", newline="\n")
        actions: dict[str, int] = {}
        for r in records.values():
            actions[r["action"]] = actions.get(r["action"], 0) + 1
        print(f"wrote {OUT} ({size} bytes, {len(records)} combinations)")
        print("actions: " + ", ".join(f"{a} {n}" for a, n in sorted(actions.items())))
        print(f"elapsed {time.perf_counter() - started:.0f} s")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
