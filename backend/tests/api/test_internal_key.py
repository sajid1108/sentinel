"""B6: internal key dependency. Missing or wrong key -> 401, and the body never names the header."""
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from sentinel.api.deps import verify_internal_key
from sentinel.settings import INTERNAL_API_KEY


@pytest.fixture
def client():
    router = APIRouter(dependencies=[Depends(verify_internal_key)])

    @router.get("/dummy")
    def dummy():
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_missing_key_is_401_without_header_name(client):
    res = client.get("/dummy")
    assert res.status_code == 401
    assert res.json() == {"detail": "Unauthorized"}
    assert "x-internal-key" not in res.text.lower()


def test_wrong_key_is_401(client):
    res = client.get("/dummy", headers={"X-Internal-Key": "wrong-key"})
    assert res.status_code == 401
    assert res.json() == {"detail": "Unauthorized"}


def test_correct_key_is_200(client):
    res = client.get("/dummy", headers={"X-Internal-Key": INTERNAL_API_KEY})
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_health_exposes_policy_version_and_clock():
    from sentinel.api.main import app
    from sentinel.policy.config import load_policy_config
    from sentinel.settings import DEMO_CLOCK

    body = TestClient(app).get("/health").json()
    cfg = load_policy_config()
    assert body["policy_version"] == "v1.0"
    assert body["policy_config_sha256"] == cfg.config_sha256[:8]
    assert body["demo_clock"] == DEMO_CLOCK.isoformat()


def test_no_cors_middleware():
    from starlette.middleware.cors import CORSMiddleware

    from sentinel.api.main import app

    assert all(m.cls is not CORSMiddleware for m in app.user_middleware)
