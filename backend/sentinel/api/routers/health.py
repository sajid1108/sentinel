from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from sentinel.policy.config import load_policy_config
from sentinel.settings import DEMO_CLOCK

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """#7: policy version, config hash prefix and the demo clock. No money, scores or thresholds."""
    model_config = ConfigDict(extra="forbid")
    status: str
    service: str
    version: str
    policy_version: str
    policy_config_sha256: str
    demo_clock: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    cfg = load_policy_config()
    return HealthResponse(status="healthy", service="sentinel", version="0.1.0", policy_version=cfg.policy.version,
                          policy_config_sha256=cfg.config_sha256[:8], demo_clock=DEMO_CLOCK.isoformat())
