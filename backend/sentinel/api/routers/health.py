from fastapi import APIRouter

from sentinel.policy.config import load_policy_config
from sentinel.settings import DEMO_CLOCK

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    cfg = load_policy_config()
    return {
        "status": "healthy",
        "service": "sentinel",
        "version": "0.1.0",
        "policy_version": cfg.policy.version,
        "policy_config_sha256": cfg.config_sha256[:8],
        "demo_clock": DEMO_CLOCK.isoformat(),
    }
