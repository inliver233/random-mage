from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.errors import ApiError, ErrorCode
from app.core.http_stream import stream_url
from app.core.security import create_jwt
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


def test_error_codes_internal_error_defined_and_used() -> None:
    assert ErrorCode.INTERNAL_ERROR.value == "INTERNAL_ERROR"
    assert _references_error_code("INTERNAL_ERROR") is True


def test_error_codes_no_match_defined_and_used() -> None:
    assert ErrorCode.NO_MATCH.value == "NO_MATCH"
    assert _references_error_code("NO_MATCH") is True


def test_error_codes_upstream_stream_error_defined_and_used() -> None:
    assert ErrorCode.UPSTREAM_STREAM_ERROR.value == "UPSTREAM_STREAM_ERROR"
    assert _references_error_code("UPSTREAM_STREAM_ERROR") is True


def test_error_codes_upstream_403_defined_and_used() -> None:
    assert ErrorCode.UPSTREAM_403.value == "UPSTREAM_403"
    assert _references_error_code("UPSTREAM_403") is True


def test_error_codes_upstream_404_defined_and_used() -> None:
    assert ErrorCode.UPSTREAM_404.value == "UPSTREAM_404"
    assert _references_error_code("UPSTREAM_404") is True


def test_error_codes_upstream_rate_limit_defined_and_used() -> None:
    assert ErrorCode.UPSTREAM_RATE_LIMIT.value == "UPSTREAM_RATE_LIMIT"
    assert _references_error_code("UPSTREAM_RATE_LIMIT") is True


def test_error_codes_upstream_rate_limit_raised_on_429() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(429, request=req))

    async def _run() -> None:
        try:
            await stream_url(
                "https://example.test/429",
                transport=transport,
                cache_control="no-store",
            )
        except ApiError as exc:
            assert exc.code == ErrorCode.UPSTREAM_RATE_LIMIT
            assert exc.status_code == 502
        else:
            raise AssertionError("expected ApiError")

    asyncio.run(_run())


def test_error_codes_invalid_upload_type_defined_and_used() -> None:
    assert ErrorCode.INVALID_UPLOAD_TYPE.value == "INVALID_UPLOAD_TYPE"
    assert _references_error_code("INVALID_UPLOAD_TYPE") is True


def test_error_codes_payload_too_large_defined_and_used() -> None:
    assert ErrorCode.PAYLOAD_TOO_LARGE.value == "PAYLOAD_TOO_LARGE"
    assert _references_error_code("PAYLOAD_TOO_LARGE") is True


def test_error_codes_payload_too_large_raised_on_import_multipart(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "error_codes_payload_too_large.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SECRET_KEY", "secret_test")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("IMPORT_MAX_BYTES", "1024")

    app = create_app()

    token = create_jwt(secret_key="secret_test", subject="admin", ttl_s=3600)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/api/imports",
            headers={"Authorization": f"Bearer {token}", "X-Request-Id": "req_test"},
            data={"dry_run": "true", "hydrate_on_import": "false", "source": "manual"},
            files={"file": ("urls.txt", b"x" * 1025, "text/plain")},
        )

        assert resp.status_code == 413
        body = resp.json()
        assert body["ok"] is False
        assert body["code"] == "PAYLOAD_TOO_LARGE"
        assert body["request_id"] == "req_test"
        assert resp.headers["X-Request-Id"] == "req_test"


def test_error_codes_unsupported_url_defined_and_used() -> None:
    assert ErrorCode.UNSUPPORTED_URL.value == "UNSUPPORTED_URL"
    assert _references_error_code("UNSUPPORTED_URL") is True


def test_error_codes_unsupported_url_returned_in_import_errors(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "error_codes_unsupported_url.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SECRET_KEY", "secret_test")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")

    app = create_app()

    token = create_jwt(secret_key="secret_test", subject="admin", ttl_s=3600)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/api/imports",
            headers={"Authorization": f"Bearer {token}", "X-Request-Id": "req_test"},
            json={"text": "not-a-url", "dry_run": True, "hydrate_on_import": False, "source": "manual"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["accepted"] == 0
        assert body["errors"][0]["code"] == "UNSUPPORTED_URL"


def test_error_codes_token_refresh_failed_defined_and_used() -> None:
    assert ErrorCode.TOKEN_REFRESH_FAILED.value == "TOKEN_REFRESH_FAILED"
    assert _references_error_code("TOKEN_REFRESH_FAILED") is True
