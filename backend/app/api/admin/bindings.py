from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import aliased

from app.api.admin.deps import get_admin_claims
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.core.time import iso_utc_ms
from app.db.models.pixiv_tokens import PixivToken
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.models.proxy_pool_endpoints import ProxyPoolEndpoint
from app.db.models.proxy_pools import ProxyPool
from app.db.models.token_proxy_bindings import TokenProxyBinding
from app.db.session import create_sessionmaker, with_sqlite_busy_retry

router = APIRouter()


def _fnv1a64(text: str) -> int:
    h = 14695981039346656037
    prime = 1099511628211
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * prime) & 0xFFFFFFFFFFFFFFFF
    return h


def _rendezvous_proxy_order(*, token_id: int, proxy_ids: list[int], salt: str) -> list[int]:
    scored = [(_fnv1a64(f"{token_id}|{pid}|{salt}"), pid) for pid in proxy_ids]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [pid for _, pid in scored]


def _compute_primary_assignments(
    *,
    token_ids: list[int],
    proxy_ids: list[int],
    max_tokens_per_proxy: int,
    salt: str,
) -> dict[int, int]:
    remaining = {pid: int(max_tokens_per_proxy) for pid in proxy_ids}
    out: dict[int, int] = {}
    for token_id in token_ids:
        for pid in _rendezvous_proxy_order(token_id=token_id, proxy_ids=proxy_ids, salt=salt):
            if remaining.get(pid, 0) > 0:
                out[token_id] = pid
                remaining[pid] -= 1
                break
    return out


async def _load_recompute_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    try:
        pool_id = int(data.get("pool_id"))
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid pool_id", status_code=400) from exc
    if pool_id <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid pool_id", status_code=400)

    raw_max = data.get("max_tokens_per_proxy", 2)
    try:
        max_tokens_per_proxy = int(raw_max)
    except Exception as exc:
        raise ApiError(
            code=ErrorCode.BAD_REQUEST,
            message="Invalid max_tokens_per_proxy",
            status_code=400,
        ) from exc

    if max_tokens_per_proxy <= 0 or max_tokens_per_proxy > 1000:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid max_tokens_per_proxy", status_code=400)

    return {"pool_id": pool_id, "max_tokens_per_proxy": max_tokens_per_proxy}


async def _load_override_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    try:
        override_proxy_id = int(data.get("override_proxy_id"))
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid override_proxy_id", status_code=400) from exc
    if override_proxy_id <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid override_proxy_id", status_code=400)

    try:
        ttl_ms = int(data.get("ttl_ms"))
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid ttl_ms", status_code=400) from exc
    if ttl_ms <= 0 or ttl_ms > 30 * 24 * 60 * 60 * 1000:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid ttl_ms", status_code=400)

    reason = str(data.get("reason") or "").strip()
    if reason and len(reason) > 200:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid reason", status_code=400)

    return {"override_proxy_id": override_proxy_id, "ttl_ms": ttl_ms, "reason": reason}


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


@router.post("/bindings/recompute")
async def recompute_bindings(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)
    now = iso_utc_ms()
    body = await _load_recompute_json(request)

    pool_id = int(body["pool_id"])
    max_tokens_per_proxy = int(body["max_tokens_per_proxy"])

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> dict[str, Any]:
        async with Session() as session:
            pool = await session.get(ProxyPool, pool_id)
            if pool is None:
                raise ApiError(code=ErrorCode.NOT_FOUND, message="Proxy pool not found", status_code=404)

            proxy_ids = (
                (
                    await session.execute(
                        sa.select(ProxyPoolEndpoint.endpoint_id)
                        .join(ProxyEndpoint, ProxyEndpoint.id == ProxyPoolEndpoint.endpoint_id)
                        .where(ProxyPoolEndpoint.pool_id == pool_id)
                        .where(ProxyPoolEndpoint.enabled == 1)
                        .where(ProxyEndpoint.enabled == 1)
                        .order_by(ProxyPoolEndpoint.endpoint_id.asc())
                    )
                )
                .scalars()
                .all()
            )
            if not proxy_ids:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="No enabled proxies in pool", status_code=400)

            token_ids = (
                (await session.execute(sa.select(PixivToken.id).order_by(PixivToken.id.asc())))
                .scalars()
                .all()
            )
            if not token_ids:
                return {"ok": True, "pool_id": str(pool_id), "recomputed": 0, "request_id": rid}

            capacity = len(proxy_ids) * max_tokens_per_proxy
            if len(token_ids) > capacity:
                raise ApiError(
                    code=ErrorCode.BAD_REQUEST,
                    message="Insufficient proxy capacity",
                    status_code=400,
                    details={
                        "token_count": len(token_ids),
                        "proxy_count": len(proxy_ids),
                        "max_tokens_per_proxy": max_tokens_per_proxy,
                    },
                )

            salt = f"pool:{pool_id}"
            assignments = _compute_primary_assignments(
                token_ids=token_ids,
                proxy_ids=proxy_ids,
                max_tokens_per_proxy=max_tokens_per_proxy,
                salt=salt,
            )

            for token_id in token_ids:
                primary_proxy_id = assignments.get(token_id)
                if primary_proxy_id is None:
                    raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="Binding recompute failed", status_code=500)

                stmt = sqlite_insert(TokenProxyBinding).values(
                    token_id=int(token_id),
                    pool_id=int(pool_id),
                    primary_proxy_id=int(primary_proxy_id),
                    override_proxy_id=None,
                    override_expires_at=None,
                    updated_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[TokenProxyBinding.token_id, TokenProxyBinding.pool_id],
                    set_={"primary_proxy_id": int(primary_proxy_id), "updated_at": now},
                )
                await session.execute(stmt)

            await session.commit()

        return {"ok": True, "pool_id": str(pool_id), "recomputed": len(token_ids), "request_id": rid}

    return await with_sqlite_busy_retry(_op)


@router.post("/bindings/{binding_id}/override")
async def set_binding_override(
    binding_id: int,
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    if binding_id <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid binding id", status_code=400)

    rid = get_or_create_request_id(request)
    now = iso_utc_ms()
    body = await _load_override_json(request)

    override_proxy_id = int(body["override_proxy_id"])
    ttl_ms = int(body["ttl_ms"])
    _reason = str(body["reason"] or "")

    expires_at = iso_utc_ms(datetime.now(timezone.utc) + timedelta(milliseconds=ttl_ms))

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> dict[str, Any]:
        async with Session() as session:
            binding = await session.get(TokenProxyBinding, binding_id)
            if binding is None:
                raise ApiError(code=ErrorCode.NOT_FOUND, message="Binding not found", status_code=404)

            proxy = await session.get(ProxyEndpoint, override_proxy_id)
            if proxy is None:
                raise ApiError(code=ErrorCode.NOT_FOUND, message="Proxy endpoint not found", status_code=404)
            if not bool(proxy.enabled):
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Proxy endpoint disabled", status_code=400)

            in_pool = (
                await session.execute(
                    sa.select(ProxyPoolEndpoint)
                    .where(ProxyPoolEndpoint.pool_id == int(binding.pool_id))
                    .where(ProxyPoolEndpoint.endpoint_id == int(override_proxy_id))
                    .where(ProxyPoolEndpoint.enabled == 1)
                )
            ).scalars().first()
            if in_pool is None:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Override proxy not in pool", status_code=400)

            binding.override_proxy_id = int(override_proxy_id)
            binding.override_expires_at = expires_at
            binding.updated_at = now
            await session.commit()

        return {
            "ok": True,
            "binding_id": str(binding_id),
            "override_proxy_id": str(override_proxy_id),
            "override_expires_at": expires_at,
            "request_id": rid,
        }

    return await with_sqlite_busy_retry(_op)


@router.post("/bindings/{binding_id}/clear-override")
async def clear_binding_override(
    binding_id: int,
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    if binding_id <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid binding id", status_code=400)

    rid = get_or_create_request_id(request)
    now = iso_utc_ms()

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> dict[str, Any]:
        async with Session() as session:
            binding = await session.get(TokenProxyBinding, binding_id)
            if binding is None:
                raise ApiError(code=ErrorCode.NOT_FOUND, message="Binding not found", status_code=404)

            binding.override_proxy_id = None
            binding.override_expires_at = None
            binding.updated_at = now
            await session.commit()

        return {"ok": True, "binding_id": str(binding_id), "request_id": rid}

    return await with_sqlite_busy_retry(_op)
