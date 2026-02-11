from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.request_id import get_or_create_request_id
from app.core.runtime_settings import fetch_runtime_settings, runtime_config_from_values

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

