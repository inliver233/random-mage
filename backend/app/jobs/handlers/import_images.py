from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.pixiv_urls import parse_pixiv_original_url
from app.db.images_upsert import upsert_image_by_illust_page
from app.db.models.images import Image
from app.db.models.imports import Import
from app.db.models.jobs import JobRow
from app.db.session import create_sessionmaker, with_sqlite_busy_retry
from app.jobs.errors import JobPermanentError

_MAX_ERRORS = 200
_CHUNK_SIZE = 200


@dataclass(frozen=True, slots=True)
class ImportLineError:
    line: int
    url: str
    code: str
    message: str


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "y", "on"}:
            return True
        if v in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _iter_lines(payload: dict[str, Any]) -> list[tuple[int, str]]:
    if "text_lines" in payload:
        raw = payload.get("text_lines")
        if not isinstance(raw, list):
            raise JobPermanentError("payload.text_lines must be a list")
        return [(i + 1, str(v)) for i, v in enumerate(raw)]

    if "text" in payload:
        text = str(payload.get("text") or "")
        return [(i, line) for i, line in enumerate(text.splitlines(), start=1)]

    if "file_ref" in payload:
        raise JobPermanentError("payload.file_ref is not supported")

    raise JobPermanentError("payload.text_lines or payload.text is required")


def _parse_payload(payload_json: str) -> dict[str, Any]:
    try:
        data = json.loads(payload_json)
    except Exception as exc:
        raise JobPermanentError("payload_json is not valid JSON") from exc
    if not isinstance(data, dict):
        raise JobPermanentError("payload_json must be an object")
    return data


def _parse_import_lines(lines: list[tuple[int, str]]) -> tuple[int, list[tuple[str, Any]], int, list[ImportLineError]]:
    total = 0
    deduped = 0
    errors: list[ImportLineError] = []
    items: list[tuple[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    for line_no, raw in lines:
        url = raw.strip()
        if not url:
            continue
        total += 1
        try:
            parsed = parse_pixiv_original_url(url)
        except Exception as exc:
            errors.append(
                ImportLineError(
                    line=int(line_no),
                    url=url,
                    code="unsupported_url",
                    message=str(exc) or "unsupported_url",
                )
            )
            continue

        key = (parsed.illust_id, parsed.page_index)
        if key in seen:
            deduped += 1
            continue
        seen.add(key)
        items.append((url, parsed))

    return total, items, deduped, errors


def _chunks(items: list[Any], *, chunk_size: int) -> list[list[Any]]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def build_import_images_handler(engine: AsyncEngine):
    Session = create_sessionmaker(engine)

    async def _handler(job: dict[str, Any]) -> None:
        payload_json = str(job.get("payload_json") or "")
        payload = _parse_payload(payload_json)

        try:
            import_id = int(payload.get("import_id"))
        except Exception as exc:
            raise JobPermanentError("payload.import_id is required") from exc
        if import_id <= 0:
            raise JobPermanentError("payload.import_id is required")

        hydrate_on_import = _as_bool(payload.get("hydrate_on_import"), default=False)

        lines = _iter_lines(payload)
        total, items, deduped, errors = _parse_import_lines(lines)

        accepted = len(items)
        illust_ids = sorted({int(parsed.illust_id) for _url, parsed in items})

        async def _op() -> None:
            async with Session() as session:
                imp = await session.get(Import, import_id)
                if imp is None:
                    raise JobPermanentError("Import not found")

                success = 0
                for chunk in _chunks(items, chunk_size=_CHUNK_SIZE):
                    for url, parsed in chunk:
                        image_id = await upsert_image_by_illust_page(
                            session,
                            illust_id=int(parsed.illust_id),
                            page_index=int(parsed.page_index),
                            ext=str(parsed.ext),
                            original_url=url,
                            proxy_path="",
                            random_key=random.random(),
                            created_import_id=int(import_id),
                        )
                        proxy_path = f"/i/{image_id}.{parsed.ext}"
                        await session.execute(
                            sa.update(Image).where(Image.id == image_id).values(proxy_path=proxy_path)
                        )
                        success += 1
                    await session.commit()

                imp.total = int(total)
                imp.accepted = int(accepted)
                imp.success = int(success)
                imp.failed = int(len(errors))
                imp.detail_json = json.dumps(
                    {"deduped": int(deduped), "errors": [asdict(e) for e in errors[:_MAX_ERRORS]]},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                await session.commit()

                if not hydrate_on_import or not illust_ids:
                    return

                existing = set(
                    (
                        await session.execute(
                            sa.select(JobRow.ref_id)
                            .where(JobRow.type == "hydrate_metadata")
                            .where(JobRow.ref_type == "import")
                            .where(JobRow.ref_id.like(f"{import_id}:%"))
                        )
                    )
                    .scalars()
                    .all()
                )

                for illust_id in illust_ids:
                    ref_id = f"{import_id}:{illust_id}"
                    if ref_id in existing:
                        continue
                    session.add(
                        JobRow(
                            type="hydrate_metadata",
                            status="pending",
                            payload_json=json.dumps(
                                {"illust_id": int(illust_id), "reason": "import"},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            ref_type="import",
                            ref_id=ref_id,
                        )
                    )
                await session.commit()

        await with_sqlite_busy_retry(_op)

    return _handler
