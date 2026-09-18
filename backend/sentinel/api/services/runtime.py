"""The services one running app holds (Phase 7 brief §A): built once in the lifespan, rebuilt by demo reset.

One engine, one ScoringService (frozen history replayed once), one ReviewService (one demo reviewer clock),
and the offline evaluation report served by GET /metrics. Writes (scoring, reviewer actions, probe rows,
demo reset) run under one lock: the FeatureBuilder's per-order cache is not thread-safe, FastAPI runs sync
routes on a thread pool, and SQLite has a single writer anyway.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from sentinel.api.services.review import DemoReviewerClock, ReviewService
from sentinel.api.services.scoring import ScoringService
from sentinel.db.models import get_engine
from sentinel.policy.config import PolicyConfig, load_policy_config
from sentinel.settings import ARTIFACTS_DIR, DATA_DIR

DB_MISSING = "Database not found. Run: python -m sentinel.cli seed-db"
EVALUATION_FILE = Path("reports") / "evaluation.json"
PRESETS_FILE = "demo_presets.json"          # written by seed-db beside the database (#34)


def presets_path(db_path: Path) -> Path:
    return Path(db_path).with_name(PRESETS_FILE)


class DatabaseMissing(RuntimeError):
    """The lifespan refuses to start without the seeded database."""


def load_evaluation(artifacts_dir: Path = ARTIFACTS_DIR) -> dict:
    return json.loads((Path(artifacts_dir) / EVALUATION_FILE).read_text(encoding="utf-8"))


@dataclass
class AppServices:
    db_path: Path
    demo_mode: bool
    cfg: PolicyConfig
    engine: object
    scoring: ScoringService
    review: ReviewService
    evaluation: dict
    clock: Callable[[], datetime]
    artifacts_dir: Path = ARTIFACTS_DIR
    data_dir: Path = DATA_DIR
    lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def start(cls, db_path: Path, *, demo_mode: bool, artifacts_dir: Path = ARTIFACTS_DIR,
              data_dir: Path = DATA_DIR, clock: Callable[[], datetime] | None = None,
              policy_config: PolicyConfig | None = None) -> "AppServices":
        db_path = Path(db_path)
        if not db_path.exists():
            raise DatabaseMissing(DB_MISSING)
        cfg = policy_config or load_policy_config()
        clock = clock if clock is not None else DemoReviewerClock()
        engine = get_engine(db_path)
        return cls(db_path=db_path, demo_mode=demo_mode, cfg=cfg, engine=engine,
                   scoring=ScoringService.start(engine, artifacts_dir, cfg), review=ReviewService(engine, clock),
                   evaluation=load_evaluation(artifacts_dir), clock=clock, artifacts_dir=Path(artifacts_dir),
                   data_dir=Path(data_dir))

    def close(self) -> None:
        self.engine.dispose()

    def reset(self) -> int:
        """Delete and re-seed the database file, then rebuild both services on it (DEMO_MODE only; the
        caller checks). The engine is disposed first so Windows can delete the file. Returns decisions."""
        from sentinel.db.seed import reset_demo          # offline code, loaded only when a reset is asked for
        with self.lock:
            self.engine.dispose()
            report = reset_demo(self.db_path, demo_mode=self.demo_mode, data_dir=self.data_dir,
                                artifacts_dir=self.artifacts_dir, policy_config=self.cfg)
            self.engine = get_engine(self.db_path)
            self.scoring = ScoringService.start(self.engine, self.artifacts_dir, self.cfg)
            self.review = ReviewService(self.engine, self.clock)
            return sum(report.by_source.values())
