from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.public.healthz import router as healthz_router
from app.db.engine import create_engine


def test_healthz_ok_includes_request_id() -> None:
    app = FastAPI()
    app.state.engine = create_engine("sqlite+aiosqlite:///:memory:")
    app.include_router(healthz_router)

    client = TestClient(app)
    resp = client.get("/healthz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["db_ok"] is True
    assert body["request_id"].startswith("req_")
    assert resp.headers["X-Request-Id"] == body["request_id"]


def test_healthz_uses_request_id_header_if_provided() -> None:
    app = FastAPI()
    app.state.engine = create_engine("sqlite+aiosqlite:///:memory:")
    app.include_router(healthz_router)

    client = TestClient(app)
    resp = client.get("/healthz", headers={"X-Request-Id": "req_test"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == "req_test"
    assert resp.headers["X-Request-Id"] == "req_test"


def test_healthz_reports_db_down_if_no_engine() -> None:
    app = FastAPI()
    app.include_router(healthz_router)

    client = TestClient(app)
    resp = client.get("/healthz", headers={"X-Request-Id": "req_test"})

    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "INTERNAL_ERROR"
    assert body["request_id"] == "req_test"

