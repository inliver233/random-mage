from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.security import create_jwt
from app.db.models.base import Base
from app.main import create_app


def test_admin_imports_json_happy_path(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "admin_imports.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SECRET_KEY", "secret_test")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")

    app = create_app()

    async def _migrate() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_migrate())

    token = create_jwt(secret_key="secret_test", subject="admin", ttl_s=3600)
    client = TestClient(app)

    text = "\n".join(
        [
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p0.jpg",
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p0.jpg",
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p1.png",
            "https://www.pixiv.net/artworks/12345678",
        ]
    )

    resp = client.post(
        "/admin/api/imports",
        headers={"Authorization": f"Bearer {token}", "X-Request-Id": "req_test"},
        json={"text": text, "dry_run": False, "hydrate_on_import": False, "source": "manual"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["accepted"] == 2
    assert body["deduped"] == 1
    assert len(body["errors"]) == 1
    assert body["import_id"].isdigit()
    assert body["job_id"].isdigit()
    assert body["request_id"] == "req_test"
    assert resp.headers["X-Request-Id"] == "req_test"

    async def _fetch_import_counts() -> tuple[int, int, int, int]:
        async with app.state.engine.connect() as conn:
            result = await conn.exec_driver_sql("SELECT total, accepted, success, failed FROM imports")
            row = result.fetchone()
            assert row is not None
            return (int(row[0]), int(row[1]), int(row[2]), int(row[3]))

    assert asyncio.run(_fetch_import_counts()) == (4, 2, 2, 1)

    async def _fetch_import_counts() -> tuple[int, int, int, int]:
        async with app.state.engine.connect() as conn:
            result = await conn.exec_driver_sql("SELECT total, accepted, success, failed FROM imports")
            row = result.fetchone()
            assert row is not None
            return (int(row[0]), int(row[1]), int(row[2]), int(row[3]))

    assert asyncio.run(_fetch_import_counts()) == (4, 2, 2, 1)


def test_admin_imports_multipart_happy_path(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "admin_imports_multipart.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SECRET_KEY", "secret_test")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")

    app = create_app()

    async def _migrate() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_migrate())

    token = create_jwt(secret_key="secret_test", subject="admin", ttl_s=3600)
    client = TestClient(app)

    text = "\n".join(
        [
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p0.jpg",
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p0.jpg",
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p1.png",
            "https://www.pixiv.net/artworks/12345678",
        ]
    )

    resp = client.post(
        "/admin/api/imports",
        headers={"Authorization": f"Bearer {token}", "X-Request-Id": "req_test"},
        data={"dry_run": "false", "hydrate_on_import": "false", "source": "manual"},
        files={"file": ("urls.txt", text.encode("utf-8"), "text/plain")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["accepted"] == 2
    assert body["deduped"] == 1
    assert len(body["errors"]) == 1
    assert body["import_id"].isdigit()
    assert body["job_id"].isdigit()
    assert body["request_id"] == "req_test"
    assert resp.headers["X-Request-Id"] == "req_test"


def test_admin_imports_dry_run_preview_does_not_write_db(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "admin_imports_dry_run.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SECRET_KEY", "secret_test")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")

    app = create_app()

    async def _migrate() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_migrate())

    token = create_jwt(secret_key="secret_test", subject="admin", ttl_s=3600)
    client = TestClient(app)

    text = "\n".join(
        [
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p0.jpg",
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p0.jpg",
            "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p1.png",
            "https://www.pixiv.net/artworks/12345678",
        ]
    )

    resp = client.post(
        "/admin/api/imports",
        headers={"Authorization": f"Bearer {token}", "X-Request-Id": "req_test"},
        json={"text": text, "dry_run": True, "hydrate_on_import": False, "source": "manual"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["accepted"] == 2
    assert body["deduped"] == 1
    assert len(body["errors"]) == 1
    assert len(body["preview"]) == 2
    assert body["import_id"] == ""
    assert body["job_id"] == ""
    assert body["request_id"] == "req_test"

    async def _count_images() -> int:
        async with app.state.engine.connect() as conn:
            result = await conn.exec_driver_sql("SELECT COUNT(*) FROM images")
            return int(result.scalar_one())

    assert asyncio.run(_count_images()) == 0
