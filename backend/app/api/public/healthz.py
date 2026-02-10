from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import ErrorCode, error_body
from app.core.request_id import get_or_create_request_id, set_request_id_header, set_request_id_on_state

router = APIRouter()


def _ensure_sqlite_dir(engine: AsyncEngine) -> None:
    url = engine.url
    if url.get_backend_name() != "sqlite":
        return
    db_path = url.database
    if not db_path or db_path == ":memory:":
        return
    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


async def _check_db(engine: AsyncEngine) -> bool:
    try:
        _ensure_sqlite_dir(engine)
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


@router.get("/healthz")
async def healthz(request: Request) -> Any:
    rid = get_or_create_request_id(request)
    set_request_id_on_state(request, rid)

    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    db_ok = await _check_db(engine) if engine is not None else False

    if db_ok:
        resp = JSONResponse(status_code=200, content={"ok": True, "db_ok": True, "request_id": rid})
    else:
        resp = JSONResponse(
            status_code=503,
            content=error_body(
                code=ErrorCode.INTERNAL_ERROR,
                message="Database unavailable",
                request_id=rid,
                details={"db_ok": False},
            ),
        )

    set_request_id_header(resp, rid)
    return resp

