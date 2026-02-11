from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import load_settings
from app.core.crypto import FieldEncryptor, mask_secret
from app.core.errors import ErrorCode
from app.core.failover import classify_pixiv_rate_limit, pixiv_rate_limit_backoff_seconds
from app.core.time import iso_utc_ms
from app.db.models.image_tags import ImageTag
from app.db.models.images import Image
from app.db.models.pixiv_tokens import PixivToken
from app.db.models.tags import Tag
from app.db.session import create_sessionmaker, with_sqlite_busy_retry
from app.jobs.errors import JobDeferError, JobPermanentError
from app.pixiv.access_token_cache import AccessTokenCache
from app.pixiv.oauth import PixivOauthConfig, PixivOauthError, refresh_access_token
from app.pixiv.refresh_backoff import refresh_backoff_seconds
from app.pixiv.token_strategy import NoTokenAvailable, TokenCandidate, choose_token

PIXIV_APP_API_BASE_URL = "https://app-api.pixiv.net"
PIXIV_ILLUST_DETAIL_URL = PIXIV_APP_API_BASE_URL + "/v1/illust/detail"

_MAX_TAGS = 200


@dataclass(frozen=True, slots=True)
class _IllustPage:
    page_index: int
    original_url: str
    ext: str


def _parse_payload(payload_json: str) -> dict[str, Any]:
    try:
        data = json.loads(payload_json)
    except Exception as exc:
        raise JobPermanentError("payload_json is not valid JSON") from exc
    if not isinstance(data, dict):
        raise JobPermanentError("payload_json must be an object")
    return data


def _parse_iso_utc_to_epoch(value: str, *, now_epoch: float) -> float:
    raw = (value or "").strip()
    if not raw:
        return 0.0
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return now_epoch + 24 * 3600
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return float(dt.astimezone(timezone.utc).timestamp())


def _normalize_iso_utc_seconds(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _derive_orientation(width: int | None, height: int | None) -> tuple[float | None, int | None]:
    if width is None or height is None or width <= 0 or height <= 0:
        return None, None
    if width > height:
        orientation = 2
    elif height > width:
        orientation = 1
    else:
        orientation = 3
    return float(width) / float(height), orientation


def _extract_tags(illust: dict[str, Any]) -> list[tuple[str, str | None]]:
    raw_tags = illust.get("tags")
    if not isinstance(raw_tags, list):
        return []
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for raw in raw_tags[: _MAX_TAGS * 2]:
        if not isinstance(raw, dict):
            continue
        name = _as_str(raw.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        translated = _as_str(raw.get("translated_name"))
        out.append((name, translated))
        if len(out) >= _MAX_TAGS:
            break
    return out


def _extract_original_urls(illust: dict[str, Any], *, page_count: int) -> list[str]:
    urls: list[str] = []
    if page_count <= 1:
        meta_single = illust.get("meta_single_page")
        if isinstance(meta_single, dict):
            url = _as_str(meta_single.get("original_image_url"))
            if url:
                return [url]
        meta_pages = illust.get("meta_pages")
        if isinstance(meta_pages, list) and meta_pages:
            first = meta_pages[0]
            if isinstance(first, dict):
                image_urls = first.get("image_urls")
                if isinstance(image_urls, dict):
                    url = _as_str(image_urls.get("original"))
                    if url:
                        return [url]
        raise ValueError("missing original_image_url")

    meta_pages = illust.get("meta_pages")
    if not isinstance(meta_pages, list) or not meta_pages:
        raise ValueError("missing meta_pages")

    for idx in range(page_count):
        page = meta_pages[idx] if idx < len(meta_pages) else None
        if not isinstance(page, dict):
            raise ValueError("invalid meta_pages")
        image_urls = page.get("image_urls")
        if not isinstance(image_urls, dict):
            raise ValueError("invalid meta_pages.image_urls")
        url = _as_str(image_urls.get("original"))
        if not url:
            raise ValueError("missing meta_pages.image_urls.original")
        urls.append(url)
    return urls


def _parse_pximg_ext(url: str) -> str:
    from app.core.pixiv_urls import parse_pixiv_original_url

    parsed = parse_pixiv_original_url(url)
    return str(parsed.ext)


def _parse_source_import_id(job: dict[str, Any]) -> int | None:
    if str(job.get("ref_type") or "").strip() != "import":
        return None
    ref_id = str(job.get("ref_id") or "").strip()
    if not ref_id:
        return None
    if ":" in ref_id:
        prefix, _rest = ref_id.split(":", 1)
    else:
        prefix = ref_id
    try:
        import_id = int(prefix)
    except Exception:
        return None
    return import_id if import_id > 0 else None


def build_hydrate_metadata_handler(
    engine: AsyncEngine,
    *,
    transport: httpx.BaseTransport | None = None,
    token_strategy: str = "least_error",
) -> Any:
    settings = load_settings()
    encryptor = FieldEncryptor.from_key(settings.field_encryption_key)
    oauth_config = PixivOauthConfig(
        client_id=settings.pixiv_oauth_client_id,
        client_secret=settings.pixiv_oauth_client_secret,
        hash_secret=(settings.pixiv_oauth_hash_secret or "").strip() or None,
    )

    Session = create_sessionmaker(engine)

    token_cache = AccessTokenCache()
    choose_lock = asyncio.Lock()
    last_token_id: int | None = None

    async def _load_tokens(now_epoch: float) -> list[TokenCandidate]:
        async with Session() as session:
            rows = (
                (await session.execute(sa.select(PixivToken).order_by(PixivToken.id.asc())))
                .scalars()
                .all()
            )
        out: list[TokenCandidate] = []
        for row in rows:
            out.append(
                TokenCandidate(
                    id=int(row.id),
                    enabled=bool(row.enabled),
                    weight=float(row.weight or 0.0),
                    error_count=int(row.error_count or 0),
                    backoff_until=_parse_iso_utc_to_epoch(str(row.backoff_until or ""), now_epoch=now_epoch),
                )
            )
        return out

    async def _choose_token_id(*, now_epoch: float, exclude_ids: set[int]) -> int:
        nonlocal last_token_id
        tokens = await _load_tokens(now_epoch)
        tokens2 = [t for t in tokens if int(t.id) not in exclude_ids]
        try:
            async with choose_lock:
                chosen, new_last = choose_token(
                    tokens2,
                    strategy=token_strategy,
                    now=now_epoch,
                    last_id=last_token_id,
                    r=random.random(),
                )
                last_token_id = int(new_last)
                return int(chosen.id)
        except NoTokenAvailable as exc:
            retry_at = exc.next_retry_at
            if retry_at is None:
                retry_at = now_epoch + 60.0
            retry_dt = datetime.fromtimestamp(float(retry_at), tz=timezone.utc)
            raise JobDeferError("No eligible token available", run_after=iso_utc_ms(retry_dt)) from exc

    async def _get_refresh_token(token_id: int) -> str:
        async with Session() as session:
            row = await session.get(PixivToken, int(token_id))
            if row is None:
                raise JobPermanentError("Token not found")
            return encryptor.decrypt_text(str(row.refresh_token_enc))

    async def _mark_token_backoff(
        token_id: int,
        *,
        now_dt: datetime,
        attempt: int,
        backoff_s: int,
        code: str,
        message: str,
        rotated_refresh_token: str | None = None,
    ) -> str | None:
        now_iso = iso_utc_ms(now_dt)
        backoff_until = iso_utc_ms(now_dt + timedelta(seconds=int(backoff_s))) if backoff_s > 0 else None
        msg = (message or "")[:500]

        async def _op() -> None:
            async with Session() as session:
                row = await session.get(PixivToken, int(token_id))
                if row is None:
                    return
                row.error_count = int(attempt)
                row.backoff_until = backoff_until
                row.last_fail_at = now_iso
                row.last_error_code = str(code)
                row.last_error_msg = msg
                row.updated_at = now_iso
                if rotated_refresh_token:
                    row.refresh_token_enc = encryptor.encrypt_text(rotated_refresh_token)
                    row.refresh_token_masked = mask_secret(rotated_refresh_token)
                await session.commit()

        await with_sqlite_busy_retry(_op)
        return backoff_until

    async def _rotate_refresh_token(token_id: int, *, rotated_refresh_token: str, now_dt: datetime) -> None:
        rotated_refresh_token = (rotated_refresh_token or "").strip()
        if not rotated_refresh_token:
            return

        now_iso = iso_utc_ms(now_dt)

        async def _op() -> None:
            async with Session() as session:
                row = await session.get(PixivToken, int(token_id))
                if row is None:
                    return
                row.refresh_token_enc = encryptor.encrypt_text(rotated_refresh_token)
                row.refresh_token_masked = mask_secret(rotated_refresh_token)
                row.updated_at = now_iso
                await session.commit()

        await with_sqlite_busy_retry(_op)

    async def _mark_token_ok(token_id: int, *, now_dt: datetime) -> None:
        now_iso = iso_utc_ms(now_dt)

        async def _op() -> None:
            async with Session() as session:
                row = await session.get(PixivToken, int(token_id))
                if row is None:
                    return
                row.error_count = 0
                row.backoff_until = None
                row.last_ok_at = now_iso
                row.last_fail_at = None
                row.last_error_code = None
                row.last_error_msg = None
                row.updated_at = now_iso
                await session.commit()

        await with_sqlite_busy_retry(_op)

    async def _get_access_token(token_id: int, *, now_dt: datetime) -> str:
        async def refresher() -> Any:
            refresh_token = await _get_refresh_token(token_id)
            token = await refresh_access_token(refresh_token=refresh_token, config=oauth_config, transport=transport)
            rotated = token.refresh_token
            if rotated:
                await _rotate_refresh_token(token_id, rotated_refresh_token=rotated, now_dt=now_dt)
            return token

        token = await token_cache.get_or_refresh(token_id, refresher=refresher)
        return str(token.access_token)

    async def _fetch_illust_detail(
        *,
        illust_id: int,
        access_token: str,
    ) -> dict[str, Any]:
        headers = oauth_config.build_headers(client_time=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        headers["Authorization"] = f"Bearer {access_token}"

        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(30.0, connect=10.0),
            "follow_redirects": True,
        }
        if transport is not None:
            client_kwargs["transport"] = transport

        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(
                PIXIV_ILLUST_DETAIL_URL,
                params={"illust_id": int(illust_id), "filter": "for_android"},
                headers=headers,
            )

        if resp.status_code != 200:
            text = resp.text
            raise httpx.HTTPStatusError(
                f"Pixiv App API error status={resp.status_code}",
                request=resp.request,
                response=resp,
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise ValueError("Pixiv App API response is not JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Pixiv App API response invalid")
        return data

    async def _persist(
        *,
        illust_id: int,
        pages: list[_IllustPage],
        width: int | None,
        height: int | None,
        aspect_ratio: float | None,
        orientation: int | None,
        x_restrict: int | None,
        ai_type: int | None,
        user_id: int | None,
        user_name: str | None,
        title: str | None,
        created_at_pixiv: str | None,
        tags: list[tuple[str, str | None]],
        source_import_id: int | None,
    ) -> None:
        now_expr = sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ','now'))")
        normalized_tag_names = [name for name, _t in tags]

        async def _op() -> None:
            async with Session() as session:
                existing = {}
                if normalized_tag_names:
                    rows = (
                        (
                            await session.execute(
                                sa.select(Tag).where(Tag.name.in_(normalized_tag_names))
                            )
                        )
                        .scalars()
                        .all()
                    )
                    existing = {str(t.name): t for t in rows}

                tag_ids: dict[str, int] = {}
                for name, translated in tags:
                    row = existing.get(name)
                    if row is None:
                        row = Tag(name=name, translated_name=translated)
                        session.add(row)
                        await session.flush()
                        existing[name] = row
                    else:
                        if translated is not None and translated != row.translated_name:
                            row.translated_name = translated
                            row.updated_at = iso_utc_ms()
                    tag_ids[name] = int(row.id)

                image_ids: list[int] = []
                for page in pages:
                    stmt = sqlite_insert(Image).values(
                        illust_id=int(illust_id),
                        page_index=int(page.page_index),
                        ext=str(page.ext),
                        original_url=str(page.original_url),
                        proxy_path="",
                        random_key=random.random(),
                        width=width,
                        height=height,
                        aspect_ratio=aspect_ratio,
                        orientation=orientation,
                        x_restrict=x_restrict,
                        ai_type=ai_type,
                        user_id=user_id,
                        user_name=user_name,
                        title=title,
                        created_at_pixiv=created_at_pixiv,
                        created_import_id=int(source_import_id) if source_import_id else None,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["illust_id", "page_index"],
                        set_={
                            "ext": stmt.excluded.ext,
                            "original_url": stmt.excluded.original_url,
                            "width": stmt.excluded.width,
                            "height": stmt.excluded.height,
                            "aspect_ratio": stmt.excluded.aspect_ratio,
                            "orientation": stmt.excluded.orientation,
                            "x_restrict": stmt.excluded.x_restrict,
                            "ai_type": stmt.excluded.ai_type,
                            "user_id": stmt.excluded.user_id,
                            "user_name": stmt.excluded.user_name,
                            "title": stmt.excluded.title,
                            "created_at_pixiv": stmt.excluded.created_at_pixiv,
                            "updated_at": now_expr,
                        },
                    ).returning(Image.id)

                    result = await session.execute(stmt)
                    image_id = int(result.scalar_one())
                    image_ids.append(image_id)

                    proxy_path = f"/i/{image_id}.{page.ext}"
                    await session.execute(
                        sa.update(Image).where(Image.id == image_id).values(proxy_path=proxy_path)
                    )

                if image_ids:
                    await session.execute(sa.delete(ImageTag).where(ImageTag.image_id.in_(image_ids)))
                    if tag_ids:
                        values = [
                            {"image_id": int(img_id), "tag_id": int(tag_id)}
                            for img_id in image_ids
                            for tag_id in tag_ids.values()
                        ]
                        stmt2 = sqlite_insert(ImageTag).values(values).on_conflict_do_nothing()
                        await session.execute(stmt2)

                await session.commit()

        await with_sqlite_busy_retry(_op)

    async def _handler(job: dict[str, Any]) -> None:
        payload_json = str(job.get("payload_json") or "")
        payload = _parse_payload(payload_json)

        try:
            illust_id = int(payload.get("illust_id"))
        except Exception as exc:
            raise JobPermanentError("payload.illust_id is required") from exc
        if illust_id <= 0:
            raise JobPermanentError("payload.illust_id is required")

        source_import_id = _parse_source_import_id(job)

        now_dt = datetime.now(timezone.utc)
        now_epoch = float(time.time())

        tried: set[int] = set()
        last_exc: BaseException | None = None

        for _ in range(0, 10):
            token_id = await _choose_token_id(now_epoch=now_epoch, exclude_ids=tried)
            tried.add(int(token_id))

            try:
                access_token = await _get_access_token(token_id, now_dt=now_dt)
            except PixivOauthError as exc:
                attempt = 0
                async with Session() as session:
                    row = await session.get(PixivToken, int(token_id))
                    if row is not None:
                        attempt = int(row.error_count or 0) + 1
                backoff_s = refresh_backoff_seconds(attempt=attempt, status_code=exc.status_code)
                await _mark_token_backoff(
                    token_id,
                    now_dt=now_dt,
                    attempt=attempt,
                    backoff_s=backoff_s,
                    code=ErrorCode.TOKEN_REFRESH_FAILED.value,
                    message="Token refresh failed",
                )
                last_exc = exc
                continue
            except Exception as exc:
                attempt = 0
                async with Session() as session:
                    row = await session.get(PixivToken, int(token_id))
                    if row is not None:
                        attempt = int(row.error_count or 0) + 1
                backoff_s = refresh_backoff_seconds(attempt=attempt, status_code=None)
                await _mark_token_backoff(
                    token_id,
                    now_dt=now_dt,
                    attempt=attempt,
                    backoff_s=backoff_s,
                    code=ErrorCode.TOKEN_REFRESH_FAILED.value,
                    message="Token refresh failed",
                )
                last_exc = exc
                continue

            try:
                data = await _fetch_illust_detail(illust_id=illust_id, access_token=access_token)
            except httpx.HTTPStatusError as exc:
                status = int(getattr(exc.response, "status_code", 0) or 0)
                body_text = getattr(exc.response, "text", None)

                if status == 404:
                    raise JobPermanentError("Pixiv illust not found") from exc

                rate_kind = classify_pixiv_rate_limit(status_code=status, body_text=body_text)
                if rate_kind is not None:
                    attempt = 0
                    async with Session() as session:
                        row = await session.get(PixivToken, int(token_id))
                        if row is not None:
                            attempt = int(row.error_count or 0) + 1
                    backoff_s = pixiv_rate_limit_backoff_seconds(attempt=attempt)
                    backoff_until = await _mark_token_backoff(
                        token_id,
                        now_dt=now_dt,
                        attempt=attempt,
                        backoff_s=backoff_s,
                        code=ErrorCode.TOKEN_BACKOFF.value,
                        message="Pixiv rate limited",
                    )
                    if backoff_until:
                        last_exc = JobDeferError("Pixiv rate limited", run_after=backoff_until)
                    continue

                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
                continue

            illust = data.get("illust") if isinstance(data, dict) else None
            if not isinstance(illust, dict):
                raise JobPermanentError("Pixiv illust detail missing illust")

            page_count = _as_int(illust.get("page_count")) or 1
            if page_count <= 0 or page_count > 1000:
                raise JobPermanentError("Pixiv illust detail invalid page_count")

            try:
                urls = _extract_original_urls(illust, page_count=int(page_count))
            except Exception as exc:
                raise JobPermanentError("Pixiv illust detail missing original urls") from exc

            pages: list[_IllustPage] = []
            for idx, url in enumerate(urls):
                try:
                    ext = _parse_pximg_ext(url)
                except Exception as exc:
                    raise JobPermanentError("Pixiv illust detail invalid original url") from exc
                pages.append(_IllustPage(page_index=int(idx), original_url=str(url), ext=ext))

            width = _as_int(illust.get("width"))
            height = _as_int(illust.get("height"))
            aspect_ratio, orientation = _derive_orientation(width, height)

            x_restrict = _as_int(illust.get("x_restrict"))
            ai_type = _as_int(illust.get("illust_ai_type"))
            if ai_type is None:
                ai_type = _as_int(illust.get("ai_type"))

            user = illust.get("user")
            user_id = _as_int(user.get("id")) if isinstance(user, dict) else None
            user_name = _as_str(user.get("name")) if isinstance(user, dict) else None

            title = _as_str(illust.get("title"))
            created_at_pixiv = None
            try:
                created_at_pixiv = _normalize_iso_utc_seconds(_as_str(illust.get("create_date")))
            except Exception:
                created_at_pixiv = None

            tags = _extract_tags(illust)

            await _persist(
                illust_id=int(illust_id),
                pages=pages,
                width=width,
                height=height,
                aspect_ratio=aspect_ratio,
                orientation=orientation,
                x_restrict=x_restrict,
                ai_type=ai_type,
                user_id=user_id,
                user_name=user_name,
                title=title,
                created_at_pixiv=created_at_pixiv,
                tags=tags,
                source_import_id=source_import_id,
            )
            await _mark_token_ok(token_id, now_dt=now_dt)
            return

        if isinstance(last_exc, JobDeferError):
            raise last_exc
        if last_exc is None:
            raise RuntimeError("hydrate_metadata failed")
        raise last_exc

    return _handler
