"""Demo database seeding (§5 "Generator outputs", §3 notes; Phase 6 `cli seed-db`). Offline code.

1. Delete and recreate the database file (never delete rows: the triggers stay honest).
2. Load the as-of-DEMO_CLOCK world (generator `as_of_view`): nothing at or after the clock.
3. policy_versions (TOML text + its line-ending-normalised SHA-256) and model_registry.
4. Exactly 250 BACKTEST_REPLAY decisions from TEST orders: every order whose SENTINEL backtest action is not
   ALLOW, filled to 250 with a seeded draw of ALLOW orders. Each is built by the scoring service's own
   assessment core from the offline feature and policy-input rows, with decided_at = graph_state_as_of = t0
   as in the backtest, and writes one DECISION_CREATED event at t0, in chronological order.
5. Deterministic: ids are uuid5 of the order id, so two seeds give byte-identical decisions and audit_events.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from sentinel.api.schemas import Action
from sentinel.api.services.scoring import (Assessment, Models, assess, load_models, seeded_decision_id,
                                           seeded_event_id, write_decision)
from sentinel.data.archetypes import SIM_START
from sentinel.data.generator import OUTPUT_FILES, SEED, as_of_view
from sentinel.db.models import (create_database, delete_database, get_engine, immediate_transaction,
                                read_connection, utc_iso)
from sentinel.evaluation.backtest import ACTIONS, sentinel_actions
from sentinel.features import definitions
from sentinel.features.builder import EVIDENCE_COLUMNS, WORLD_TABLES, signal_inputs_from_row
from sentinel.models import predict, registry
from sentinel.policy.config import PolicyConfig, load_policy_config
from sentinel.settings import ARTIFACTS_DIR, CONFIG_DIR, DATA_DIR, DB_PATH, DEMO_CLOCK, DEMO_MODE

SEEDED_DECISIONS = 250
TEST = "TEST"
POLICY_FILE = CONFIG_DIR / "policy_v1_0.toml"
EVALUATION_FILE = Path("reports") / "evaluation.json"
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"             # identical to db.models.utc_iso


@dataclass
class SeedReport:
    path: Path
    elapsed_s: float
    world_rows: dict[str, int]
    test_orders: int
    non_allow_test_orders: int
    allow_filled: int
    by_action: dict[str, int]
    by_source: dict[str, int]
    notes: list[str] = field(default_factory=list)


def _iso(series: pd.Series) -> list[str | None]:
    text = series.dt.tz_convert("UTC").dt.strftime(_UTC_FORMAT)
    return [None if pd.isna(v) else v for v in text]


def _none(values) -> list:
    return [None if (v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA) else v for v in values]


def read_world(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    return {t: pd.read_parquet(Path(data_dir) / OUTPUT_FILES[t]) for t in WORLD_TABLES}


def _insert_world(conn, world: dict[str, pd.DataFrame]) -> dict[str, int]:
    a, i, o, ln, ev = (world[t] for t in WORLD_TABLES)
    conn.executemany("INSERT INTO accounts VALUES (?, ?, ?)",
                     zip(a["account_id"], _iso(a["created_at"]), a["source"]))
    conn.executemany("INSERT INTO identifiers VALUES (?, ?, ?, ?, ?)",
                     zip(i["identifier_id"], i["kind"], i["is_multi_tenant"].astype(int).tolist(),
                         _iso(i["multi_tenant_set_at"]), i["display_label"]))
    conn.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        zip(o["order_id"], o["account_id"], _iso(o["placed_at"]), o["order_value_inr"].tolist(),
            o["discount_pct"].tolist(), o["n_items"].astype(int).tolist(),
            o["n_variants_same_product"].astype(int).tolist(), o["primary_category"], o["delivery_speed"],
            o["payment_method"], o["device_id"], o["address_id"], _none(o["payment_token_id"].astype(object)),
            o["source"], _none(o["split"].astype(object))))
    conn.executemany("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     zip(ln["order_id"], ln["line_no"].astype(int).tolist(), ln["sku_id"], ln["product_id"],
                         ln["variant"], ln["category"], ln["unit_price_inr"].tolist(),
                         ln["quantity"].astype(int).tolist()))
    conn.executemany("INSERT INTO order_events VALUES (?, ?, ?, ?, ?)",
                     zip(ev["event_id"].astype(int).tolist(), ev["order_id"], ev["event_type"],
                         _iso(ev["occurred_at"]), ev["attributes_json"]))
    return {t: len(world[t]) for t in WORLD_TABLES}


def _insert_governance(conn, cfg: PolicyConfig, artifacts_dir: Path) -> None:
    toml_text = POLICY_FILE.read_text(encoding="utf-8")
    conn.execute("INSERT INTO policy_versions VALUES (?, ?, ?, ?)",
                 (cfg.policy.version, toml_text, cfg.config_sha256, utc_iso(SIM_START)))
    reg = registry.load_registry(artifacts_dir)
    evaluation = json.loads((artifacts_dir / EVALUATION_FILE).read_text(encoding="utf-8"))
    metrics = {m["model"]: {k: m[k] for k in ("pr_auc", "pr_auc_ci95", "brier", "ece_10bin_quantile")}
               for m in evaluation["models"]}
    for name, entry in sorted(reg["models"].items()):
        model_name = name.upper()
        conn.execute("INSERT INTO model_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            entry["model_version"], model_name, entry["trained_at"], json.dumps(entry["train_window"], sort_keys=True),
            json.dumps(entry["calibration_window"], sort_keys=True), entry["calibration_method"].upper(),
            entry["feature_set_version"], json.dumps(entry["feature_list"]), entry["sklearn_version"],
            entry["sha256"], json.dumps(metrics.get(model_name, {}), sort_keys=True)))


@dataclass(frozen=True)
class ReplaySelection:
    rows: pd.DataFrame            # chosen TEST rows (features + policy inputs), chronological
    backtest_actions: dict[str, Action]
    test_orders: int
    non_allow: int
    allow_filled: int
    notes: tuple[str, ...]


def select_replay_orders(features: pd.DataFrame, policy: pd.DataFrame, models: Models, cfg: PolicyConfig,
                         n: int = SEEDED_DECISIONS, seed: int = SEED) -> ReplaySelection:
    """Every TEST order the SENTINEL backtest does not ALLOW, then a seeded draw of ALLOW orders up to n."""
    test = features[features["split"] == TEST].merge(
        policy.drop(columns=["split", "t0"]), on="order_id", how="inner", validate="one_to_one",
        suffixes=("", "_policy"))
    test = test.sort_values(["t0", "order_id"], kind="stable").reset_index(drop=True)
    p_abuse = predict(models.bundles["abuse"], test)
    p_return = predict(models.bundles["return"], test)
    actions = np.array([ACTIONS[i] for i in sentinel_actions(test, p_abuse, p_return, cfg)], dtype=object)
    test = test.assign(_p_abuse=p_abuse, _action=actions)
    non_allow = test[test["_action"] != Action.ALLOW]
    notes = []
    if len(non_allow) > n:
        chosen = non_allow.sort_values(["_p_abuse", "order_id"], ascending=[False, True], kind="stable").head(n)
        notes.append(f"{len(non_allow)} non-ALLOW TEST orders exceed {n}; kept the {n} with the highest p_abuse")
        filled = 0
    else:
        allow_ids = sorted(test.loc[test["_action"] == Action.ALLOW, "order_id"])
        filled = n - len(non_allow)
        rng = np.random.default_rng(seed)
        drawn = set(np.asarray(allow_ids, dtype=object)[rng.choice(len(allow_ids), size=filled, replace=False)])
        chosen = pd.concat([non_allow, test[test["order_id"].isin(drawn)]])
    chosen = chosen.sort_values(["t0", "order_id"], kind="stable").reset_index(drop=True)
    return ReplaySelection(chosen, dict(zip(chosen["order_id"], chosen["_action"])), len(test), len(non_allow),
                           filled, tuple(notes))


def _value(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def matured_counts(returns: int, rate) -> tuple[int, int] | None:
    """(returns, matured orders) from the policy-inputs row, which keeps the raw rate returns / matured.

    The count is recovered exactly whenever it is defined: no rate means no matured order; a zero rate
    leaves the count unknown (and RETURN_HIGH_HISTORY cannot fire then), so None - the counts-free text.
    """
    if rate is None or pd.isna(rate):
        return returns, 0
    if rate == 0:
        return None
    return returns, round(returns / rate)


def replay_assessment(row: dict, models: Models, cfg: PolicyConfig) -> Assessment:
    """One TEST order through the scoring core, from its offline rows, exactly as the backtest decides it."""
    t0 = row["t0"].to_pydatetime()
    matured = matured_counts(int(row["matured_returns"]), row["matured_return_rate"])
    features = {name: row[name] for name in definitions.all_features()}
    result = assess(features=features, signal_inputs=signal_inputs_from_row(row),
                    discounted_links=[],             # not in the offline rows; see DEVIATIONS (Phase 6)
                    device_evidence={c: _value(row[c]) for c in EVIDENCE_COLUMNS}, matured=matured,
                    models=models, cfg=cfg, order_value=float(row["order_value_inr"]),
                    clv_inr=float(row["clv_inr"]), decided_at=t0,
                    graph_state_as_of=row["graph_state_as_of"].to_pydatetime())
    if isinstance(result, str):
        raise RuntimeError(f"seeding {row['order_id']}: {result}")
    return result


def seed_database(db_path: Path = DB_PATH, data_dir: Path = DATA_DIR, artifacts_dir: Path = ARTIFACTS_DIR,
                  policy_config: PolicyConfig | None = None) -> SeedReport:
    start = time.perf_counter()
    cfg = policy_config or load_policy_config()
    models = load_models(artifacts_dir)
    world = as_of_view(read_world(data_dir), DEMO_CLOCK)
    features = pd.read_parquet(Path(data_dir) / "features.parquet")
    policy = pd.read_parquet(Path(data_dir) / "policy_inputs.parquet")
    missing = [c for c in EVIDENCE_COLUMNS if c not in policy.columns]
    if missing:
        raise RuntimeError(f"policy_inputs.parquet lacks {missing}; run `python -m sentinel.cli build-features`")
    selection = select_replay_orders(features, policy, models, cfg)

    delete_database(db_path)
    create_database(db_path)
    engine = get_engine(db_path)
    try:
        with immediate_transaction(engine) as conn:
            world_rows = _insert_world(conn, world)
            _insert_governance(conn, cfg, artifacts_dir)
            versions = models.versions
            by_action: Counter = Counter()
            for row in selection.rows.to_dict("records"):
                assessment = replay_assessment(row, models, cfg)
                t0 = row["t0"].to_pydatetime()
                write_decision(conn, decision_id=seeded_decision_id(row["order_id"]),
                               event_id=seeded_event_id(row["order_id"]), order_id=row["order_id"], scored_at=t0,
                               features_as_of=t0, assessment=assessment, versions=versions,
                               source="BACKTEST_REPLAY")
                by_action[assessment.decision.selected_action.value] += 1
            by_source = dict(conn.execute("SELECT source, COUNT(*) FROM decisions GROUP BY source").fetchall())
        with read_connection(engine) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        engine.dispose()                                  # release the file (Windows) before anyone deletes it
    return SeedReport(Path(db_path), time.perf_counter() - start, world_rows, selection.test_orders,
                      selection.non_allow, selection.allow_filled,
                      {a.value: by_action.get(a.value, 0) for a in Action}, by_source, list(selection.notes))


class DemoModeOff(RuntimeError):
    """reset-demo was asked for with DEMO_MODE off."""


def reset_demo(db_path: Path = DB_PATH, *, demo_mode: bool = DEMO_MODE, **seed_kwargs) -> SeedReport:
    """Delete the database file (and -wal / -shm), then seed again. Refuses unless DEMO_MODE is on.

    Callers holding an engine on this file must dispose it first; seed_database disposes its own.
    """
    if not demo_mode:
        raise DemoModeOff("reset-demo refuses to run: DEMO_MODE is off (SENTINEL_DEMO_MODE)")
    delete_database(db_path)
    return seed_database(db_path, **seed_kwargs)
