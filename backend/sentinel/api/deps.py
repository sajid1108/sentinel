import hmac

from fastapi import Header, HTTPException
from datetime import datetime
from sentinel.settings import INTERNAL_API_KEY, DEMO_CLOCK


def verify_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    """Verify the internal API key. Returns 401 on failure."""
    if x_internal_key is None or not hmac.compare_digest(x_internal_key, INTERNAL_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


def get_reviewer_id(x_reviewer_id: str = Header(default="reviewer-placeholder-01")) -> str:
    return x_reviewer_id


def get_demo_clock() -> datetime:
    return DEMO_CLOCK
