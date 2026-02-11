from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.core.time import iso_utc_ms
from app.db.models.hydration_runs import HydrationRun
from app.db.models.jobs import JobRow
from app.db.session import create_sessionmaker, with_sqlite_busy_retry

router = APIRouter()


async def _load_create_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    run_type = str(data.get("type") or "backfill").strip().lower() or "backfill"
    if run_type not in {"backfill", "manual"}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid type", status_code=400)

    criteria = data.get("criteria")
    if criteria is None:
        criteria = {}
    if not isinstance(criteria, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid criteria", status_code=400)

    return {"type": run_type, "criteria": criteria}


@router.post("/hydration-runs")
async def create_hydration_run(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)
    now = iso_utc_ms()
    body = await _load_create_json(request)

    run_type = str(body["type"])
    criteria = dict(body["criteria"])

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> tuple[int, int]:
        async with Session() as session:
            run = HydrationRun(
                type=run_type,
                status="pending",
                criteria_json=json.dumps(criteria, separators=(",", ":"), ensure_ascii=False),
                cursor_json=None,
                total=None,
                processed=0,
                success=0,
                failed=0,
                started_at=None,
                finished_at=None,
                last_error=None,
                updated_at=now,
            )
            session.add(run)
            await session.flush()

            job = JobRow(
                type="hydrate_metadata",
                status="pending",
                payload_json=json.dumps(
                    {"hydration_run_id": int(run.id), "criteria": criteria},
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                last_error=None,
                priority=0,
                run_after=None,
                attempt=0,
                max_attempts=3,
                locked_by=None,
                locked_at=None,
                ref_type="hydration_run",
                ref_id=str(int(run.id)),
                updated_at=now,
            )
            session.add(job)
            await session.flush()
            await session.commit()
            return int(run.id), int(job.id)

    run_id, job_id = await with_sqlite_busy_retry(_op)

    return {
        "ok": True,
        "hydration_run_id": str(run_id),
        "job_id": str(job_id),
        "request_id": rid,
    }

