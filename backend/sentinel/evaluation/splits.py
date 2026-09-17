"""Offline modelling frames (§5 Timeline, §7.2 P8, P11).

Labels and ground truth are read here, in evaluation/, and nowhere in the serving packages.
The split of an order is the orders table's split column, carried into features.parquet.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from sentinel.data.generator import OUTPUT_FILES
from sentinel.settings import DATA_DIR

FEATURES_FILE = "features.parquet"
POLICY_INPUTS_FILE = "policy_inputs.parquet"
LABEL_COLUMNS = ["order_id", "return_label", "return_type", "returned_value_fraction", "abuse_status", "abuse_label"]
TRUTH_COLUMNS = ["account_id", "archetype", "ring_id"]


@dataclass(frozen=True)
class OfflineData:
    frame: pd.DataFrame          # features + labels, one row per order (training input)
    policy_inputs: pd.DataFrame  # one row per order, never model features
    truth: pd.DataFrame          # order_id, account_id, archetype, ring_id (evaluation only)


def _require(path: Path, command: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `python -m sentinel.cli {command}` first")
    return path


def load_offline_data(data_dir: Path = DATA_DIR) -> OfflineData:
    """From the generator's Parquet files and build-features' output in data_dir."""
    data_dir = Path(data_dir)
    return offline_data(
        features=pd.read_parquet(_require(data_dir / FEATURES_FILE, "build-features")),
        policy_inputs=pd.read_parquet(_require(data_dir / POLICY_INPUTS_FILE, "build-features")),
        labels=pd.read_parquet(_require(data_dir / OUTPUT_FILES["order_labels"], "generate")),
        orders=pd.read_parquet(_require(data_dir / OUTPUT_FILES["orders"], "generate")),
        truth=pd.read_parquet(_require(data_dir / OUTPUT_FILES["sim_ground_truth"], "generate")))


def offline_data(features: pd.DataFrame, policy_inputs: pd.DataFrame, labels: pd.DataFrame, orders: pd.DataFrame,
                 truth: pd.DataFrame) -> OfflineData:
    frame = features.merge(labels[LABEL_COLUMNS], on="order_id", how="left", validate="one_to_one")
    if len(frame) != len(orders) or frame["abuse_status"].isna().any():
        raise ValueError("features and labels do not cover the same orders; regenerate and rebuild features")
    split_check = frame[["order_id", "split"]].merge(orders[["order_id", "split"]], on="order_id",
                                                     suffixes=("", "_orders"))
    if len(split_check) != len(frame) or not (split_check["split"] == split_check["split_orders"]).all():
        raise ValueError("features.parquet splits differ from orders.split; rebuild features")
    order_truth = orders[["order_id", "account_id"]].merge(truth[TRUTH_COLUMNS], on="account_id", how="left",
                                                          validate="many_to_one")
    return OfflineData(frame.sort_values(["t0", "order_id"], kind="stable").reset_index(drop=True),
                       policy_inputs.sort_values(["t0", "order_id"], kind="stable").reset_index(drop=True),
                       order_truth)
