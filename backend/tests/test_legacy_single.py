from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.db.models.base import Base
from app.db.models.images import Image
from app.db.session import create_sessionmaker
from app.main import create_app


def test_legacy_single_streams_bytes(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "legacy_single.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)

    app = create_app()

    async def _seed() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(app.state.engine)
        async with Session() as session:
            session.add(
                Image(
                    illust_id=123,
                    page_index=0,
                    ext="jpg",
                    original_url="https://example.test/origin.jpg",
                    proxy_path="/i/1.jpg",
                    random_key=0.5,
                )
            )
            await session.commit()

        await app.state.engine.dispose()

    asyncio.run(_seed())

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers.get("Referer") == "https://www.pixiv.net/"
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"img-bytes")

    app.state.httpx_transport = httpx.MockTransport(handler)

    with TestClient(app) as client:
        resp = client.get("/123.jpg", headers={"X-Request-Id": "req_test"})
        assert resp.status_code == 200
        assert resp.content == b"img-bytes"
        assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        assert resp.headers["X-Request-Id"] == "req_test"


def test_legacy_single_ext_mismatch_returns_404(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "legacy_single_mismatch.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)

    app = create_app()

    async def _seed() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(app.state.engine)
        async with Session() as session:
            session.add(
                Image(
                    illust_id=123,
                    page_index=0,
                    ext="jpg",
                    original_url="https://example.test/origin.jpg",
                    proxy_path="/i/1.jpg",
                    random_key=0.5,
                )
            )
            await session.commit()

        await app.state.engine.dispose()

    asyncio.run(_seed())

    with TestClient(app) as client:
        resp = client.get("/123.png", headers={"X-Request-Id": "req_test"})
        assert resp.status_code == 404
        body = resp.json()
        assert body["ok"] is False
        assert body["code"] == "NOT_FOUND"
        assert body["request_id"] == "req_test"

