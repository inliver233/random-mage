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


async def _set_run_and_job_status(
    request: Request,
    *,
    run_id: int,
    target_status: str,
    allowed_from: set[str],
    job_status: str,
) -> dict[str, Any]:
    if run_id <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid hydration_run id", status_code=400)

    rid = get_or_create_request_id(request)
    now = iso_utc_ms()

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> dict[str, Any]:
        async with Session() as session:
            run = await session.get(HydrationRun, run_id)
            if run is None:
                raise ApiError(code=ErrorCode.NOT_FOUND, message="Hydration run not found", status_code=404)

            if str(run.status) not in allowed_from:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported status transition", status_code=400)

            run.status = target_status
            run.updated_at = now
            if target_status in {"canceled", "completed", "failed"} and run.finished_at is None:
                run.finished_at = now

            job = (
                (
                    await session.execute(
                        sa.select(JobRow)
                        .where(JobRow.ref_type == "hydration_run", JobRow.ref_id == str(run_id))
                        .order_by(JobRow.id.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if job is not None:
                job.status = job_status
                if job_status in {"pending", "canceled", "paused", "dlq"}:
                    job.run_after = None
                    job.locked_by = None
                    job.locked_at = None
                job.updated_at = now

            await session.commit()

        return {
            "ok": True,
            "hydration_run_id": str(run_id),
            "status": target_status,
            "job_status": job_status if job is not None else "",
            "request_id": rid,
        }

    return await with_sqlite_busy_retry(_op)


@router.post("/hydration-runs/{run_id}/pause")
async def pause_hydration_run(
    run_id: int,
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    return await _set_run_and_job_status(
        request,
        run_id=run_id,
        target_status="paused",
        allowed_from={"pending", "running"},
        job_status="paused",
    )


@router.post("/hydration-runs/{run_id}/resume")
async def resume_hydration_run(
    run_id: int,
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    return await _set_run_and_job_status(
        request,
        run_id=run_id,
        target_status="pending",
        allowed_from={"paused"},
        job_status="pending",
    )


@router.post("/hydration-runs/{run_id}/cancel")
async def cancel_hydration_run(
    run_id: int,
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    return await _set_run_and_job_status(
        request,
        run_id=run_id,
        target_status="canceled",
        allowed_from={"pending", "running", "paused"},
        job_status="canceled",
    )
