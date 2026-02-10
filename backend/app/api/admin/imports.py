from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.admin.deps import get_admin_claims
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.core.pixiv_urls import parse_pixiv_original_url
from app.db.images_upsert import upsert_image_by_illust_page
from app.db.models.images import Image
from app.db.models.imports import Import
from app.db.models.jobs import JobRow
from app.db.session import create_sessionmaker

router = APIRouter()


class ImportCreateRequest(BaseModel):
    text: str = Field(min_length=1)
    dry_run: bool = False
    hydrate_on_import: bool = False
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class ImportErrorItem:
    line: int
    url: str
    code: str
    message: str


def _parse_import_text(text: str) -> tuple[int, list[tuple[str, Any]], int, list[ImportErrorItem]]:
    total = 0
    deduped = 0
    errors: list[ImportErrorItem] = []
    items: list[tuple[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    for line_no, raw in enumerate(text.splitlines(), start=1):
        url = raw.strip()
        if not url:
            continue
        total += 1
        try:
            parsed = parse_pixiv_original_url(url)
        except Exception as exc:
            errors.append(
                ImportErrorItem(
                    line=line_no,
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


@router.post("/imports")
async def create_import(
    body: ImportCreateRequest,
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    if body.dry_run:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="dry_run not implemented yet", status_code=400)

    rid = get_or_create_request_id(request)

    total, items, deduped, errors = _parse_import_text(body.text)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    accepted = len(items)
    success = 0

    async with Session() as session:
        imp = Import(created_by=str(_claims.get("sub") or ""), source=body.source)
        session.add(imp)
        await session.flush()

        for url, parsed in items:
            image_id = await upsert_image_by_illust_page(
                session,
                illust_id=parsed.illust_id,
                page_index=parsed.page_index,
                ext=parsed.ext,
                original_url=url,
                proxy_path="",
                random_key=random.random(),
                created_import_id=imp.id,
            )

            proxy_path = f"/i/{image_id}.{parsed.ext}"
            await session.execute(
                sa.update(Image).where(Image.id == image_id).values(proxy_path=proxy_path)
            )

            success += 1

        imp.total = total
        imp.accepted = accepted
        imp.success = success
        imp.failed = len(errors)
        imp.detail_json = json.dumps(
            {
                "deduped": deduped,
                "errors": [asdict(e) for e in errors[:200]],
            },
            ensure_ascii=False,
        )

        job = JobRow(
            type="import_images",
            status="completed",
            payload_json=json.dumps(
                {
                    "import_id": imp.id,
                    "accepted": accepted,
                    "deduped": deduped,
                    "failed": len(errors),
                },
                ensure_ascii=False,
            ),
            ref_type="import",
            ref_id=str(imp.id),
        )
        session.add(job)
        await session.flush()

        await session.commit()

        import_id = imp.id
        job_id = job.id

    return {
        "ok": True,
        "import_id": str(import_id),
        "job_id": str(job_id),
        "accepted": accepted,
        "deduped": deduped,
        "errors": [asdict(e) for e in errors[:200]],
        "request_id": rid,
    }

