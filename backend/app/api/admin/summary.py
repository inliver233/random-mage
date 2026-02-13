from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.request_id import get_or_create_request_id
from app.db.session import with_sqlite_busy_retry

router = APIRouter()


def _worker_last_seen_from_value_json(value_json: str | None) -> str | None:
    if value_json is None:
        return None
    raw = str(value_json or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict):
        at = data.get("at")
        return str(at) if isinstance(at, str) and at.strip() else None
    if isinstance(data, str):
        return data.strip() or None
    return None


@router.get("/summary")
async def get_summary(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    engine = request.app.state.engine

    async def _op() -> dict[str, Any]:
        async with engine.connect() as conn:
            images_total = int((await conn.exec_driver_sql("SELECT COUNT(*) FROM images;")).scalar_one())
            images_enabled = int(
                (await conn.exec_driver_sql("SELECT COUNT(*) FROM images WHERE status=1;")).scalar_one()
            )

            tokens_total = int((await conn.exec_driver_sql("SELECT COUNT(*) FROM pixiv_tokens;")).scalar_one())
            tokens_enabled = int(
                (await conn.exec_driver_sql("SELECT COUNT(*) FROM pixiv_tokens WHERE enabled=1;")).scalar_one()
            )

            proxies_total = int((await conn.exec_driver_sql("SELECT COUNT(*) FROM proxy_endpoints;")).scalar_one())
            proxies_enabled = int(
                (await conn.exec_driver_sql("SELECT COUNT(*) FROM proxy_endpoints WHERE enabled=1;")).scalar_one()
            )

            pools_total = int((await conn.exec_driver_sql("SELECT COUNT(*) FROM proxy_pools;")).scalar_one())
            pools_enabled = int(
                (await conn.exec_driver_sql("SELECT COUNT(*) FROM proxy_pools WHERE enabled=1;")).scalar_one()
            )

            bindings_total = int((await conn.exec_driver_sql("SELECT COUNT(*) FROM token_proxy_bindings;")).scalar_one())

            jobs_counts: dict[str, int] = {}
            rows = (await conn.exec_driver_sql("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status;")).fetchall()
            for status, count in rows:
                jobs_counts[str(status)] = int(count)

            worker_last_seen_json = (
                await conn.exec_driver_sql("SELECT value_json FROM runtime_settings WHERE key = ?;", ("worker.last_seen_at",))
            ).scalar_one_or_none()
            worker_last_seen_at = _worker_last_seen_from_value_json(str(worker_last_seen_json) if worker_last_seen_json is not None else None)

        return {
            "images": {"total": images_total, "enabled": images_enabled},
            "tokens": {"total": tokens_total, "enabled": tokens_enabled},
            "proxies": {"endpoints_total": proxies_total, "endpoints_enabled": proxies_enabled},
            "proxy_pools": {"total": pools_total, "enabled": pools_enabled},
            "bindings": {"total": bindings_total},
            "jobs": {"counts": jobs_counts},
            "worker": {"last_seen_at": worker_last_seen_at},
        }

    counts = await with_sqlite_busy_retry(_op)
    return {"ok": True, "counts": counts, "request_id": rid}

