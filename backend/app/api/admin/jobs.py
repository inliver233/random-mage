from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.db.models.jobs import JobRow
from app.db.session import create_sessionmaker

router = APIRouter()

_ALLOWED_JOB_STATUSES = {"pending", "running", "paused", "canceled", "completed", "failed", "dlq"}


@router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = 50,
    cursor: str | None = None,
    status: str | None = None,
    type: str | None = None,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    if limit < 1 or limit > 200:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported limit", status_code=400)

    cursor_i: int | None = None
    cursor_raw = (cursor or "").strip()
    if cursor_raw:
        if not cursor_raw.isdigit():
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported cursor", status_code=400)
        cursor_i = int(cursor_raw)
        if cursor_i <= 0:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported cursor", status_code=400)

    status_norm = (status or "").strip().lower() or None
    if status_norm is not None and status_norm not in _ALLOWED_JOB_STATUSES:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported status", status_code=400)

    type_norm = (type or "").strip() or None
    if type_norm is not None and len(type_norm) > 100:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported type", status_code=400)

    rid = get_or_create_request_id(request)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    stmt = sa.select(JobRow).order_by(JobRow.id.desc()).limit(limit + 1)
    if cursor_i is not None:
        stmt = stmt.where(JobRow.id < cursor_i)
    if status_norm is not None:
        stmt = stmt.where(JobRow.status == status_norm)
    if type_norm is not None:
        stmt = stmt.where(JobRow.type == type_norm)

    async with Session() as session:
        rows = ((await session.execute(stmt)).scalars().all())

    items_rows = rows[:limit]
    next_cursor = int(items_rows[-1].id) if len(rows) > limit and items_rows else None

    items = [
        {
            "id": str(row.id),
            "type": row.type,
            "status": row.status,
            "priority": int(row.priority),
            "run_after": row.run_after,
            "attempt": int(row.attempt),
            "max_attempts": int(row.max_attempts),
            "last_error": row.last_error,
            "locked_by": row.locked_by,
            "locked_at": row.locked_at,
            "ref_type": row.ref_type,
            "ref_id": row.ref_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in items_rows
    ]

    return {
        "ok": True,
        "items": items,
        "next_cursor": str(next_cursor) if next_cursor is not None else "",
        "request_id": rid,
    }

