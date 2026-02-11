from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.request_id import get_or_create_request_id
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.session import create_sessionmaker

router = APIRouter()


@router.get("/proxies/endpoints")
async def list_proxy_endpoints(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)
    async with Session() as session:
        endpoints = (
            (
                await session.execute(sa.select(ProxyEndpoint).order_by(ProxyEndpoint.id.desc()))
            )
            .scalars()
            .all()
        )

    items = [
        {
            "id": str(p.id),
            "scheme": p.scheme,
            "host": p.host,
            "port": int(p.port),
            "username": p.username,
            "enabled": bool(p.enabled),
            "source": p.source,
            "source_ref": p.source_ref,
            "last_latency_ms": p.last_latency_ms,
            "last_ok_at": p.last_ok_at,
            "last_fail_at": p.last_fail_at,
            "success_count": int(p.success_count or 0),
            "failure_count": int(p.failure_count or 0),
            "blacklisted_until": p.blacklisted_until,
            "last_error": p.last_error,
        }
        for p in endpoints
    ]

    return {"ok": True, "items": items, "request_id": rid}

