from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.request_id import get_or_create_request_id
from app.db.models.proxy_pools import ProxyPool
from app.db.session import create_sessionmaker

router = APIRouter()


@router.get("/proxy-pools")
async def list_proxy_pools(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)
    async with Session() as session:
        pools = (
            (await session.execute(sa.select(ProxyPool).order_by(ProxyPool.id.desc())))
            .scalars()
            .all()
        )

    items = [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "enabled": bool(p.enabled),
        }
        for p in pools
    ]

    return {"ok": True, "items": items, "request_id": rid}

