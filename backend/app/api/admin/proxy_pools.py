from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError

from app.api.admin.deps import get_admin_claims
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.db.models.proxy_pools import ProxyPool
from app.db.session import create_sessionmaker

router = APIRouter()


def _parse_bool(value: Any, *, default: bool) -> bool:
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


async def _load_create_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    name = str(data.get("name") or "").strip()
    if not name:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing name", status_code=400)
    if len(name) > 100:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported name", status_code=400)

    desc_raw = data.get("description")
    description = str(desc_raw).strip() if desc_raw is not None else None
    description = description if description else None

    enabled = _parse_bool(data.get("enabled"), default=True)
    return {"name": name, "description": description, "enabled": enabled}


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


@router.post("/proxy-pools")
async def create_proxy_pool(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)
    body = await _load_create_json(request)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async with Session() as session:
        row = ProxyPool(
            name=str(body["name"]),
            description=body["description"],
            enabled=1 if bool(body["enabled"]) else 0,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Proxy pool name exists", status_code=400) from exc
        await session.refresh(row)

    return {"ok": True, "pool_id": str(row.id), "request_id": rid}
