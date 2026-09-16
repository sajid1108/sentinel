from datetime import datetime, timezone, timedelta
from pathlib import Path
import os

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

# Fixed demo clock - never use wall clock for feature windows
DEMO_CLOCK = datetime(2026, 9, 1, 10, 30, 0, tzinfo=IST)

# HMAC secret for identifier hashing
HMAC_SECRET = os.environ.get("SENTINEL_HMAC_SECRET", "demo-secret-do-not-use-in-production")

# Internal API key
INTERNAL_API_KEY = os.environ.get("SENTINEL_INTERNAL_API_KEY", "sentinel-internal-dev-key")

# Demo mode flag
DEMO_MODE = os.environ.get("SENTINEL_DEMO_MODE", "true").lower() == "true"

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
CONFIG_DIR = Path(__file__).resolve().parent / "config"
DB_PATH = DATA_DIR / "sentinel.db"
