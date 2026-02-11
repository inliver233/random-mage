from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.errors import ErrorCode
from app.db.models.base import Base
from app.db.models.images import Image
from app.db.session import create_sessionmaker
from app.main import create_app


def _references_error_code(name: str) -> bool:
    backend_dir = Path(__file__).resolve().parents[1]
    app_dir = backend_dir / "app"
    errors_py = app_dir / "core" / "errors.py"
    needle = f"ErrorCode.{name}"
    for path in app_dir.rglob("*.py"):
        if path == errors_py:
            continue
        if needle in path.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def test_error_codes_random_json_success_is_http_200(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "error_codes_random_ok.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.api.public.random.random.random", lambda: 0.0)

    app = create_app()

    async def _seed() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(app.state.engine)
        async with Session() as session:
            session.add(
                Image(
                    illust_id=12345678,
                    page_index=0,
                    ext="jpg",
                    original_url="https://example.test/ok.jpg",
                    proxy_path="/i/1.jpg",
                    random_key=0.5,
                    x_restrict=0,
                )
            )
            await session.commit()
        await app.state.engine.dispose()

    asyncio.run(_seed())

    with TestClient(app) as client:
        resp = client.get("/random", params={"format": "json", "attempts": 1, "r18_strict": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["code"] == "OK"


def test_error_codes_random_json_no_match_is_http_404(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "error_codes_random_no_match.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.api.public.random.random.random", lambda: 0.0)

    app = create_app()

    async def _seed() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(app.state.engine)
        async with Session() as session:
            session.add(
                Image(
                    illust_id=12345678,
                    page_index=0,
                    ext="jpg",
                    original_url="https://example.test/no_match.jpg",
                    proxy_path="/i/1.jpg",
                    random_key=0.5,
                    width=100,
                    height=100,
                    x_restrict=0,
                )
            )
            await session.commit()
        await app.state.engine.dispose()

    asyncio.run(_seed())

    with TestClient(app) as client:
        resp = client.get(
            "/random",
            params={
                "format": "json",
                "attempts": 1,
                "r18_strict": 0,
                "min_width": 999999,
            },
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["ok"] is False
        assert body["code"] == "NO_MATCH"


def test_error_codes_bad_request_defined_and_used() -> None:
    assert ErrorCode.BAD_REQUEST.value == "BAD_REQUEST"
    assert _references_error_code("BAD_REQUEST") is True


def test_error_codes_unauthorized_defined_and_used() -> None:
    assert ErrorCode.UNAUTHORIZED.value == "UNAUTHORIZED"
    assert _references_error_code("UNAUTHORIZED") is True


def test_error_codes_forbidden_defined_and_used() -> None:
    assert ErrorCode.FORBIDDEN.value == "FORBIDDEN"
    assert _references_error_code("FORBIDDEN") is True


def test_error_codes_not_found_defined_and_used() -> None:
    assert ErrorCode.NOT_FOUND.value == "NOT_FOUND"
    assert _references_error_code("NOT_FOUND") is True
