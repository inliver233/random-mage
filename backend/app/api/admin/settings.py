from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.core.runtime_settings import (
    fetch_runtime_settings,
    runtime_config_from_values,
    set_runtime_setting,
)

router = APIRouter()

_DEFAULT_SETTINGS = {
    "random": {"default_attempts": 3, "default_r18_strict": True, "fail_cooldown_ms": 600_000},
    "proxy": {"allowlist_domains": []},
}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        v = item.strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return True
        if v in {"false", "0", "no", "n", "off"}:
            return False
    return None


async def _load_settings_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    settings = data.get("settings") if "settings" in data else data
    if not isinstance(settings, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid settings", status_code=400)
    if not settings:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing fields", status_code=400)

    return settings


@router.get("/settings")
async def get_settings(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    engine = request.app.state.engine
    values = await fetch_runtime_settings(engine)
    runtime = runtime_config_from_values(values)

    allowlist_domains = _as_str_list(values.get("proxy.allowlist_domains"))

    random_defaults = dict(_DEFAULT_SETTINGS["random"])
    if isinstance(runtime.random_defaults, dict):
        for k in list(random_defaults.keys()):
            if k in runtime.random_defaults:
                random_defaults[k] = runtime.random_defaults[k]

    return {
        "ok": True,
        "settings": {
            "proxy": {
                "enabled": bool(runtime.proxy_enabled),
                "fail_closed": bool(runtime.proxy_fail_closed),
                "route_mode": runtime.proxy_route_mode,
                "allowlist_domains": allowlist_domains,
            },
            "random": random_defaults,
            "security": {"hide_origin_url_in_public_json": bool(runtime.hide_origin_url_in_public_json)},
            "rate_limit": dict(runtime.rate_limit),
        },
        "request_id": rid,
    }


@router.put("/settings")
async def update_settings(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    rid = get_or_create_request_id(request)
    body = await _load_settings_json(request)

    actor = str(_claims.get("sub") or "admin").strip() or "admin"
    updated_by = f"admin:{actor}"

    updates: list[tuple[str, Any]] = []
    proxy_enabled_override: bool | None = None
    proxy_fail_closed_override: bool | None = None

    proxy = body.get("proxy")
    if proxy is not None:
        if not isinstance(proxy, dict):
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid proxy", status_code=400)

        if "enabled" in proxy:
            v = _as_bool(proxy.get("enabled"))
            if v is None:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid proxy.enabled", status_code=400)
            proxy_enabled_override = bool(v)
            updates.append(("proxy.enabled", bool(v)))

        if "fail_closed" in proxy:
            v = _as_bool(proxy.get("fail_closed"))
            if v is None:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid proxy.fail_closed", status_code=400)
            proxy_fail_closed_override = bool(v)
            updates.append(("proxy.fail_closed", bool(v)))

        if "route_mode" in proxy:
            route_mode = str(proxy.get("route_mode") or "").strip().lower()
            if route_mode not in {"pixiv_only", "all", "allowlist", "off"}:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid proxy.route_mode", status_code=400)
            updates.append(("proxy.route_mode", route_mode))

        if "allowlist_domains" in proxy:
            domains = _as_str_list(proxy.get("allowlist_domains"))
            if len(domains) > 200 or any(len(d) > 200 for d in domains):
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid proxy.allowlist_domains", status_code=400)
            updates.append(("proxy.allowlist_domains", domains))

    random = body.get("random")
    if random is not None:
        if not isinstance(random, dict):
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid random", status_code=400)

        defaults: dict[str, Any] = {}
        for key in ("default_attempts", "default_r18_strict", "fail_cooldown_ms"):
            if key not in random:
                continue
            if key in {"default_attempts", "fail_cooldown_ms"}:
                try:
                    n = int(random.get(key))
                except Exception as exc:
                    raise ApiError(code=ErrorCode.BAD_REQUEST, message=f"Invalid random.{key}", status_code=400) from exc
                if n < 0 or n > 10_000_000:
                    raise ApiError(code=ErrorCode.BAD_REQUEST, message=f"Invalid random.{key}", status_code=400)
                defaults[key] = n
            else:
                v = _as_bool(random.get(key))
                if v is None:
                    raise ApiError(code=ErrorCode.BAD_REQUEST, message=f"Invalid random.{key}", status_code=400)
                defaults[key] = bool(v)

        if defaults:
            updates.append(("random.defaults", defaults))

    security = body.get("security")
    if security is not None:
        if not isinstance(security, dict):
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid security", status_code=400)

        if "hide_origin_url_in_public_json" in security:
            v = _as_bool(security.get("hide_origin_url_in_public_json"))
            if v is None:
                raise ApiError(
                    code=ErrorCode.BAD_REQUEST,
                    message="Invalid security.hide_origin_url_in_public_json",
                    status_code=400,
                )
            updates.append(("security.hide_origin_url_in_public_json", bool(v)))

    rate_limit = body.get("rate_limit")
    if rate_limit is not None:
        if not isinstance(rate_limit, dict):
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid rate_limit", status_code=400)

        for key, value in rate_limit.items():
            k = str(key or "").strip()
            if not k or len(k) > 100:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid rate_limit key", status_code=400)
            updates.append((f"rate_limit.{k}", value))

    if not updates:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing fields", status_code=400)

    engine = request.app.state.engine

    if proxy_enabled_override is not None or proxy_fail_closed_override is not None:
        values = await fetch_runtime_settings(engine)
        runtime = runtime_config_from_values(values)
        desired_enabled = proxy_enabled_override if proxy_enabled_override is not None else bool(runtime.proxy_enabled)
        desired_fail_closed = (
            proxy_fail_closed_override if proxy_fail_closed_override is not None else bool(runtime.proxy_fail_closed)
        )
        if desired_enabled and desired_fail_closed:
            async with engine.connect() as conn:
                result = await conn.exec_driver_sql("SELECT COUNT(*) FROM proxy_endpoints WHERE enabled=1;")
                enabled_proxy_count = int(result.scalar_one())
            if enabled_proxy_count <= 0:
                raise ApiError(
                    code=ErrorCode.PROXY_REQUIRED,
                    message="Proxy required (fail-closed) but no enabled proxies",
                    status_code=400,
                )

    for key, value in updates:
        await set_runtime_setting(engine, key=key, value=value, updated_by=updated_by)

    return {"ok": True, "updated": len(updates), "request_id": rid}
