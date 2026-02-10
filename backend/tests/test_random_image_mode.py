from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.db.models.base import Base
from app.db.models.images import Image
from app.db.session import create_sessionmaker
from app.main import create_app


def test_random_image_streams_bytes(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "random_image.db"
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

    asyncio.run(_seed())

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers.get("Referer") == "https://www.pixiv.net/"
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"img-bytes")

    app.state.httpx_transport = httpx.MockTransport(handler)

    client = TestClient(app)
    resp = client.get("/random", headers={"X-Request-Id": "req_test"})
    assert resp.status_code == 200
    assert resp.content == b"img-bytes"
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Request-Id"] == "req_test"


def test_random_image_no_match_returns_404(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "random_image_empty.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)

    app = create_app()

    async def _migrate() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_migrate())

    client = TestClient(app)
    resp = client.get("/random", headers={"X-Request-Id": "req_test"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "NO_MATCH"
    assert body["request_id"] == "req_test"

