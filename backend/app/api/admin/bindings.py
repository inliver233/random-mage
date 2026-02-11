from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import aliased

from app.api.admin.deps import get_admin_claims
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.core.time import iso_utc_ms
from app.db.models.pixiv_tokens import PixivToken
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.models.proxy_pools import ProxyPool
from app.db.models.token_proxy_bindings import TokenProxyBinding
from app.db.session import create_sessionmaker

router = APIRouter()


@router.get("/bindings")
async def list_bindings(
    request: Request,
    pool_id: int,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    if int(pool_id) <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid pool_id", status_code=400)

    rid = get_or_create_request_id(request)
    now = iso_utc_ms()

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    Primary = aliased(ProxyEndpoint)
    Override = aliased(ProxyEndpoint)

    async with Session() as session:
        rows = (
            (
                await session.execute(
                    sa.select(TokenProxyBinding, PixivToken.label, ProxyPool.name, Primary, Override)
                    .join(PixivToken, PixivToken.id == TokenProxyBinding.token_id)
                    .join(ProxyPool, ProxyPool.id == TokenProxyBinding.pool_id)
                    .join(Primary, Primary.id == TokenProxyBinding.primary_proxy_id)
                    .outerjoin(Override, Override.id == TokenProxyBinding.override_proxy_id)
                    .where(TokenProxyBinding.pool_id == int(pool_id))
                    .order_by(TokenProxyBinding.id.asc())
                )
            )
            .all()
        )

    items: list[dict[str, Any]] = []
    for binding, token_label, pool_name, primary_proxy, override_proxy in rows:
        override_active = False
        if binding.override_proxy_id is not None and binding.override_expires_at:
            override_active = str(binding.override_expires_at) > now

        effective_proxy_id = binding.override_proxy_id if override_active else binding.primary_proxy_id
        effective_mode = "override" if override_active else "primary"

        items.append(
            {
                "id": str(binding.id),
                "token": {"id": str(binding.token_id), "label": token_label},
                "pool": {"id": str(binding.pool_id), "name": pool_name},
                "primary_proxy": {
                    "id": str(primary_proxy.id),
                    "scheme": primary_proxy.scheme,
                    "host": primary_proxy.host,
                    "port": int(primary_proxy.port),
                    "username": primary_proxy.username,
                },
                "override_proxy": (
                    {
                        "id": str(override_proxy.id),
                        "scheme": override_proxy.scheme,
                        "host": override_proxy.host,
                        "port": int(override_proxy.port),
                        "username": override_proxy.username,
                    }
                    if override_proxy is not None
                    else None
                ),
                "override_expires_at": binding.override_expires_at,
                "effective_proxy_id": str(effective_proxy_id),
                "effective_mode": effective_mode,
            }
        )

    return {"ok": True, "items": items, "request_id": rid}

