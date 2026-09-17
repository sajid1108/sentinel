"""Score the three §11 demo requests offline through the real models and the real policy (Phase 4 gate).

builder replayed to DEMO_CLOCK -> features_for_request -> calibrated p_return, p_abuse -> decide().
Nothing here knows which demo is which: every request goes through the same path.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from sentinel.api.schemas import PolicyDecision, ScoreOrderRequest
from sentinel.data.demo_orders import demo_requests
from sentinel.data.generator import OUTPUT_FILES
from sentinel.features.builder import WORLD_TABLES, FeatureBuilder
from sentinel.models import predict
from sentinel.policy.config import PolicyConfig
from sentinel.policy.engine import decide
from sentinel.policy.guardrails import DecisionContext, corroborating_signals
from sentinel.settings import DATA_DIR, DEMO_CLOCK


@dataclass(frozen=True)
class DemoScore:
    order_id: str
    features: dict
    clv_inr: float
    p_return: float
    p_abuse: float
    counted_signals: tuple[str, ...]
    decision: PolicyDecision


def load_world(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    return {t: pd.read_parquet(Path(data_dir) / OUTPUT_FILES[t]) for t in WORLD_TABLES}


def score_demos(bundles: dict[str, dict], cfg: PolicyConfig, world=None) -> list[DemoScore]:
    builder = FeatureBuilder.replay(world if world is not None else load_world(), DEMO_CLOCK)
    out = []
    for payload in demo_requests():
        request = ScoreOrderRequest.model_validate(payload)
        features = builder.features_for_request(request)
        row = pd.DataFrame([features])
        p_return = float(predict(bundles["return"], row)[0])
        p_abuse = float(predict(bundles["abuse"], row)[0])
        signals = corroborating_signals(builder.signal_inputs(request))
        clv = builder.clv_inr(request.account_id, request.placed_at)
        ctx = DecisionContext(p_abuse=p_abuse, p_return=p_return, order_value_inr=features["order_value_inr"],
                              clv_inr=clv, signals=signals, decided_at=DEMO_CLOCK,
                              graph_state_as_of=builder.graph_state_as_of)
        out.append(DemoScore(request.order_id, features, clv, p_return, p_abuse,
                             tuple(s.signal for s in signals if s.present and s.counts_for_corroboration),
                             decide(ctx, cfg)))
    return out
