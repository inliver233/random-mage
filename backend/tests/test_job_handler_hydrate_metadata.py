from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import sqlalchemy as sa
from cryptography.fernet import Fernet

from app.core.crypto import FieldEncryptor
from app.db.engine import create_engine
from app.db.models.base import Base
from app.db.models.images import Image
from app.db.models.imports import Import
from app.db.models.jobs import JobRow
from app.db.models.pixiv_tokens import PixivToken
from app.db.models.tags import Tag
from app.db.session import create_sessionmaker
from app.db.tags_get import get_tag_names_for_image
from app.jobs.claim import claim_next_job
from app.jobs.dispatch import JobDispatcher
from app.jobs.executor import execute_claimed_job
from app.jobs.handlers.hydrate_metadata import build_hydrate_metadata_handler


def _sqlite_url(db_path: Path) -> str:
    return "sqlite+aiosqlite:///" + db_path.as_posix()


def _parse_iso_utc_ms(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def test_job_handler_hydrate_metadata_happy_path_updates_images_and_tags(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "handler_hydrate_metadata.db"
    engine = create_engine(_sqlite_url(db_path))

    field_key = Fernet.generate_key().decode("ascii")
    encryptor = FieldEncryptor.from_key(field_key)

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", field_key)
    monkeypatch.setenv("PIXIV_OAUTH_CLIENT_ID", "cid_test")
    monkeypatch.setenv("PIXIV_OAUTH_CLIENT_SECRET", "csec_test")
    monkeypatch.setenv("PIXIV_OAUTH_HASH_SECRET", "hsec_test")

    refresh_token = "rt_old"
    access_token = "at_test"

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://oauth.secure.pixiv.net/auth/token":
            body = (req.content or b"").decode("utf-8")
            assert f"refresh_token={refresh_token}" in body
            return httpx.Response(
                200,
                json={
                    "response": {
                        "access_token": access_token,
                        "token_type": "bearer",
                        "expires_in": 3600,
                        "refresh_token": "rt_rotated",
                        "scope": "",
                        "user": {"id": 123},
                    }
                },
            )

        if str(req.url).startswith("https://app-api.pixiv.net/v1/illust/detail"):
            assert req.headers.get("Authorization") == f"Bearer {access_token}"
            return httpx.Response(
                200,
                json={
                    "illust": {
                        "id": 111,
                        "title": "title_test",
                        "user": {"id": 999, "name": "user_test"},
                        "x_restrict": 0,
                        "illust_ai_type": 1,
                        "width": 1200,
                        "height": 800,
                        "create_date": "2020-01-01T00:00:00+00:00",
                        "page_count": 2,
                        "tags": [
                            {"name": "tag1", "translated_name": "t1"},
                            {"name": "tag2"},
                        ],
                        "meta_pages": [
                            {
                                "image_urls": {
                                    "original": "https://i.pximg.net/img-original/img/2020/01/01/00/00/00/111_p0.jpg"
                                }
                            },
                            {
                                "image_urls": {
                                    "original": "https://i.pximg.net/img-original/img/2020/01/01/00/00/00/111_p1.png"
                                }
                            },
                        ],
                    }
                },
            )

        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(engine)

        async with Session() as session:
            token_row = PixivToken(
                label="acc1",
                enabled=1,
                refresh_token_enc=encryptor.encrypt_text(refresh_token),
                refresh_token_masked="***",
                weight=1.0,
            )
            session.add(token_row)

            imp = Import(created_by="admin", source="manual")
            session.add(imp)
            await session.commit()
            await session.refresh(token_row)
            await session.refresh(imp)

            img0 = Image(
                illust_id=111,
                page_index=0,
                ext="jpg",
                original_url="https://i.pximg.net/img-original/old/111_p0.jpg",
                proxy_path="",
                random_key=0.123,
                created_import_id=int(imp.id),
            )
            session.add(img0)
            await session.flush()
            img0.proxy_path = f"/i/{int(img0.id)}.jpg"

            job = JobRow(
                type="hydrate_metadata",
                status="pending",
                payload_json=json.dumps({"illust_id": 111, "reason": "import"}, ensure_ascii=False, separators=(",", ":")),
                ref_type="import",
                ref_id=f"{int(imp.id)}:111",
            )
            session.add(job)
            await session.commit()

            existing_image_id = int(img0.id)
            import_id = int(imp.id)

        dispatcher = JobDispatcher()
        dispatcher.register("hydrate_metadata", build_hydrate_metadata_handler(engine, transport=transport))

        claimed = await claim_next_job(engine, worker_id="w1")
        assert claimed is not None

        transition = await execute_claimed_job(engine, dispatcher, job_row=claimed, worker_id="w1")
        assert transition is not None
        assert transition.status.value == "completed"

        async with Session() as session:
            images = (
                (
                    await session.execute(
                        sa.select(Image).where(Image.illust_id == 111).order_by(Image.page_index.asc())
                    )
                )
                .scalars()
                .all()
            )
            assert len(images) == 2
            assert int(images[0].id) == existing_image_id
            assert images[0].ext == "jpg"
            assert images[1].ext == "png"
            assert images[0].proxy_path == f"/i/{int(images[0].id)}.jpg"
            assert images[1].proxy_path == f"/i/{int(images[1].id)}.png"
            assert images[0].created_import_id == import_id
            assert images[1].created_import_id == import_id

            assert images[0].width == 1200
            assert images[0].height == 800
            assert images[0].orientation == 2
            assert images[0].aspect_ratio and abs(float(images[0].aspect_ratio) - 1.5) < 1e-6
            assert images[0].x_restrict == 0
            assert images[0].ai_type == 1
            assert images[0].user_id == 999
            assert images[0].user_name == "user_test"
            assert images[0].title == "title_test"
            assert images[0].created_at_pixiv == "2020-01-01T00:00:00Z"

            tags = ((await session.execute(sa.select(Tag).order_by(Tag.name.asc()))).scalars().all())
            assert [t.name for t in tags] == ["tag1", "tag2"]
            assert {t.name: t.translated_name for t in tags} == {"tag1": "t1", "tag2": None}

            names0 = await get_tag_names_for_image(session, image_id=int(images[0].id))
            names1 = await get_tag_names_for_image(session, image_id=int(images[1].id))
            assert names0 == ["tag1", "tag2"]
            assert names1 == ["tag1", "tag2"]

            token_db = await session.get(PixivToken, int(token_row.id))
            assert token_db is not None
            assert int(token_db.error_count or 0) == 0
            assert token_db.backoff_until is None
            assert token_db.last_ok_at is not None and token_db.last_ok_at

        await engine.dispose()

    asyncio.run(_run())


def test_job_handler_hydrate_metadata_missing_illust_id_moves_to_dlq(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "handler_hydrate_metadata_missing_illust_id.db"
    engine = create_engine(_sqlite_url(db_path))

    field_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", field_key)
    monkeypatch.setenv("PIXIV_OAUTH_CLIENT_ID", "cid_test")
    monkeypatch.setenv("PIXIV_OAUTH_CLIENT_SECRET", "csec_test")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(engine)
        async with Session() as session:
            session.add(
                JobRow(
                    type="hydrate_metadata",
                    status="pending",
                    payload_json=json.dumps({}, ensure_ascii=False, separators=(",", ":")),
                )
            )
            await session.commit()

        dispatcher = JobDispatcher()
        dispatcher.register("hydrate_metadata", build_hydrate_metadata_handler(engine, transport=httpx.MockTransport(lambda r: httpx.Response(500))))

        claimed = await claim_next_job(engine, worker_id="w1")
        assert claimed is not None

        transition = await execute_claimed_job(engine, dispatcher, job_row=claimed, worker_id="w1")
        assert transition is not None
        assert transition.status.value == "dlq"

        async with Session() as session:
            row = (
                (
                    await session.execute(
                        sa.select(JobRow).where(JobRow.id == int(claimed["id"]))
                    )
                )
                .scalars()
                .one()
            )
            assert row.status == "dlq"

        await engine.dispose()

    asyncio.run(_run())


def test_job_handler_hydrate_metadata_rate_limit_defers_job_and_updates_token(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "handler_hydrate_metadata_rate_limit.db"
    engine = create_engine(_sqlite_url(db_path))

    field_key = Fernet.generate_key().decode("ascii")
    encryptor = FieldEncryptor.from_key(field_key)

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", field_key)
    monkeypatch.setenv("PIXIV_OAUTH_CLIENT_ID", "cid_test")
    monkeypatch.setenv("PIXIV_OAUTH_CLIENT_SECRET", "csec_test")

    refresh_token = "rt_old"

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://oauth.secure.pixiv.net/auth/token":
            return httpx.Response(
                200,
                json={
                    "response": {
                        "access_token": "at_test",
                        "token_type": "bearer",
                        "expires_in": 3600,
                        "refresh_token": None,
                        "scope": "",
                        "user": {"id": 123},
                    }
                },
            )
        if str(req.url).startswith("https://app-api.pixiv.net/v1/illust/detail"):
            return httpx.Response(403, text="Rate Limit")
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(engine)
        async with Session() as session:
            token_row = PixivToken(
                label="acc1",
                enabled=1,
                refresh_token_enc=encryptor.encrypt_text(refresh_token),
                refresh_token_masked="***",
                weight=1.0,
            )
            session.add(token_row)
            session.add(
                JobRow(
                    type="hydrate_metadata",
                    status="pending",
                    payload_json=json.dumps({"illust_id": 222}, ensure_ascii=False, separators=(",", ":")),
                )
            )
            await session.commit()
            await session.refresh(token_row)
            token_id = int(token_row.id)

        dispatcher = JobDispatcher()
        dispatcher.register("hydrate_metadata", build_hydrate_metadata_handler(engine, transport=transport))

        claimed = await claim_next_job(engine, worker_id="w1")
        assert claimed is not None

        transition = await execute_claimed_job(engine, dispatcher, job_row=claimed, worker_id="w1")
        assert transition is not None
        assert transition.status.value == "failed"
        assert transition.run_after is not None and transition.run_after
        assert transition.attempt == 0

        async with Session() as session:
            job_row = await session.get(JobRow, int(claimed["id"]))
            assert job_row is not None
            assert job_row.status == "failed"
            assert int(job_row.attempt) == 0
            assert job_row.run_after is not None and job_row.run_after

            token_db = await session.get(PixivToken, token_id)
            assert token_db is not None
            assert int(token_db.error_count or 0) == 1
            assert token_db.backoff_until is not None and token_db.backoff_until
            assert token_db.last_error_code == "TOKEN_BACKOFF"

            now = datetime.now(timezone.utc)
            run_after_dt = _parse_iso_utc_ms(str(job_row.run_after))
            delta_s = (run_after_dt - now).total_seconds()
            assert 10.0 < delta_s < 180.0

        await engine.dispose()

    asyncio.run(_run())

