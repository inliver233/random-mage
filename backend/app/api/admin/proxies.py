from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse, urlunparse

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.crypto import FieldEncryptor
from app.core.errors import ApiError, ErrorCode
from app.core.proxy_uri import parse_proxy_uri
from app.core.request_id import get_or_create_request_id
from app.core.time import iso_utc_ms
from app.db.models.jobs import JobRow
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.models.proxy_pool_endpoints import ProxyPoolEndpoint
from app.db.models.proxy_pools import ProxyPool
from app.db.models.token_proxy_bindings import TokenProxyBinding
from app.db.session import create_sessionmaker, with_sqlite_busy_retry
from app.easy_proxies.client import EasyProxiesError, easy_proxies_auth, easy_proxies_export

router = APIRouter()


def _mask_proxy_uri(*, scheme: str, host: str, port: int, username: str, password_set: bool) -> str:
    scheme = (scheme or "").strip().lower()
    host = (host or "").strip()
    username = (username or "").strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    auth = ""
    if username:
        auth = f"{username}@"
        if password_set:
            auth = f"{username}:***@"

    return f"{scheme}://{auth}{host}:{int(port)}"


def _sanitize_source_ref(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        parsed = urlparse(raw)
    except Exception:
        return raw[:200]

    if not parsed.scheme or not parsed.netloc:
        return raw[:200]

    host = parsed.hostname
    if not host:
        return raw[:200]

    port = parsed.port
    netloc = f"{host}:{int(port)}" if port else host
    path = parsed.path or ""

    return urlunparse((parsed.scheme, netloc, path, "", "", ""))


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

        endpoint_ids = [int(p.id) for p in endpoints]

        pools_by_eid: dict[int, list[dict[str, Any]]] = {}
        if endpoint_ids:
            pool_rows = (
                (
                    await session.execute(
                        sa.select(
                            ProxyPoolEndpoint.endpoint_id,
                            ProxyPoolEndpoint.pool_id,
                            ProxyPoolEndpoint.enabled,
                            ProxyPoolEndpoint.weight,
                            ProxyPool.name,
                            ProxyPool.enabled,
                        )
                        .join(ProxyPool, ProxyPool.id == ProxyPoolEndpoint.pool_id)
                        .where(ProxyPoolEndpoint.endpoint_id.in_(endpoint_ids))
                        .order_by(ProxyPoolEndpoint.pool_id.asc())
                    )
                )
                .all()
            )
            for endpoint_id, pool_id, member_enabled, weight, pool_name, pool_enabled in pool_rows:
                pools_by_eid.setdefault(int(endpoint_id), []).append(
                    {
                        "id": str(pool_id),
                        "name": str(pool_name),
                        "pool_enabled": bool(pool_enabled),
                        "member_enabled": bool(member_enabled),
                        "weight": int(weight or 0),
                    }
                )

        primary_counts: dict[int, int] = {}
        override_counts: dict[int, int] = {}
        if endpoint_ids:
            rows = (
                (
                    await session.execute(
                        sa.select(TokenProxyBinding.primary_proxy_id, sa.func.count())
                        .where(TokenProxyBinding.primary_proxy_id.in_(endpoint_ids))
                        .group_by(TokenProxyBinding.primary_proxy_id)
                    )
                )
                .all()
            )
            for pid, c in rows:
                primary_counts[int(pid)] = int(c)

            rows2 = (
                (
                    await session.execute(
                        sa.select(TokenProxyBinding.override_proxy_id, sa.func.count())
                        .where(TokenProxyBinding.override_proxy_id.is_not(None))
                        .where(TokenProxyBinding.override_proxy_id.in_(endpoint_ids))
                        .group_by(TokenProxyBinding.override_proxy_id)
                    )
                )
                .all()
            )
            for pid, c in rows2:
                if pid is None:
                    continue
                override_counts[int(pid)] = int(c)

    now_iso = iso_utc_ms()

    items = [
        {
            "id": str(p.id),
            "enabled": bool(p.enabled),
            "source": str(p.source or "manual"),
            "source_ref": _sanitize_source_ref(p.source_ref),
            "uri_masked": _mask_proxy_uri(
                scheme=str(p.scheme),
                host=str(p.host),
                port=int(p.port),
                username=str(p.username or ""),
                password_set=bool(str(p.password_enc or "").strip()),
            ),
            "latency_ms": float(p.last_latency_ms) if p.last_latency_ms is not None else None,
            "status": (
                "blacklisted"
                if (p.blacklisted_until and str(p.blacklisted_until) > str(now_iso))
                else "ok"
                if p.last_ok_at and (not p.last_fail_at or str(p.last_ok_at) >= str(p.last_fail_at))
                else "fail"
                if p.last_fail_at
                else "unknown"
            ),
            "blacklisted_until": p.blacklisted_until,
            "last_error": p.last_error,
            "success_count": int(p.success_count or 0),
            "failure_count": int(p.failure_count or 0),
            "last_ok_at": p.last_ok_at,
            "last_fail_at": p.last_fail_at,
            "pools": pools_by_eid.get(int(p.id), []),
            "bindings": {
                "primary_count": int(primary_counts.get(int(p.id), 0)),
                "override_count": int(override_counts.get(int(p.id), 0)),
            },
        }
        for p in endpoints
    ]

    return {"ok": True, "items": items, "request_id": rid}


def _parse_conflict_policy(value: Any) -> str:
    v = str(value or "").strip().lower() or "skip"
    if v not in {"skip", "overwrite"}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported conflict_policy", status_code=400)
    return v


def _parse_easy_conflict_policy(value: Any) -> str:
    v = str(value or "").strip().lower() or "skip_non_easy_proxies"
    if v not in {"skip_non_easy_proxies", "skip", "overwrite"}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported conflict_policy", status_code=400)
    return v


def _parse_bool_strict(value: Any) -> bool | None:
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
    return None


async def _load_import_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    text = str(data.get("text") or "")
    if not text.strip():
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing text", status_code=400)

    source = str(data.get("source") or "manual").strip() or "manual"
    conflict_policy = _parse_conflict_policy(data.get("conflict_policy"))

    return {"text": text, "source": source, "conflict_policy": conflict_policy}


async def _load_update_endpoint_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)
    if "enabled" not in data:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing enabled", status_code=400)

    enabled = _parse_bool_strict(data.get("enabled"))
    if enabled is None:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported enabled", status_code=400)

    return {"enabled": bool(enabled)}


async def _load_easy_import_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    base_url = str(data.get("base_url") or "").strip()
    password = str(data.get("password") or "").strip()
    if not base_url:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing base_url", status_code=400)

    conflict_policy = _parse_easy_conflict_policy(data.get("conflict_policy"))
    return {"base_url": base_url, "password": password, "conflict_policy": conflict_policy}


async def _load_probe_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    out: dict[str, Any] = {}

    if "probe_url" in data:
        probe_url = str(data.get("probe_url") or "").strip()
        if probe_url:
            if len(probe_url) > 2000:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid probe_url", status_code=400)
            if "://" not in probe_url:
                raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid probe_url", status_code=400)
            out["probe_url"] = probe_url

    if "timeout_ms" in data:
        raw = data.get("timeout_ms")
        try:
            timeout_ms = int(raw)
        except Exception as exc:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid timeout_ms", status_code=400) from exc
        if timeout_ms <= 0 or timeout_ms > 600_000:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid timeout_ms", status_code=400)
        out["timeout_ms"] = int(timeout_ms)

    if "concurrency" in data:
        raw = data.get("concurrency")
        try:
            concurrency = int(raw)
        except Exception as exc:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid concurrency", status_code=400) from exc
        if concurrency < 1 or concurrency > 200:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid concurrency", status_code=400)
        out["concurrency"] = int(concurrency)

    return out


@router.post("/proxies/endpoints/import")
async def import_proxy_endpoints(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    body = await _load_import_json(request)

    text = str(body["text"])
    source = str(body["source"])
    conflict_policy = str(body["conflict_policy"])

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    now = iso_utc_ms()

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    settings = request.app.state.settings
    encryptor: FieldEncryptor | None = None

    async def _op() -> None:
        nonlocal created, updated, skipped, errors, encryptor
        async with Session() as session:
            for line_no, raw in enumerate(text.splitlines(), start=1):
                uri = raw.strip()
                if not uri:
                    continue
                try:
                    parsed = parse_proxy_uri(uri)
                except Exception:
                    errors.append({"line": line_no, "code": "invalid_proxy_uri", "message": "invalid_proxy_uri"})
                    continue

                username = (parsed.username or "").strip()
                password = parsed.password
                password_enc = ""
                if password:
                    if encryptor is None:
                        try:
                            encryptor = FieldEncryptor.from_key(settings.field_encryption_key)
                        except Exception:
                            errors.append(
                                {
                                    "line": line_no,
                                    "code": "encryption_not_configured",
                                    "message": "代理包含密码，但未配置加密密钥（FIELD_ENCRYPTION_KEY）",
                                }
                            )
                            continue
                    password_enc = encryptor.encrypt_text(password)

                existing = (
                    (
                        await session.execute(
                            sa.select(ProxyEndpoint).where(
                                ProxyEndpoint.scheme == parsed.scheme,
                                ProxyEndpoint.host == parsed.host,
                                ProxyEndpoint.port == int(parsed.port),
                                ProxyEndpoint.username == username,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )

                if existing is None:
                    session.add(
                        ProxyEndpoint(
                            scheme=parsed.scheme,
                            host=parsed.host,
                            port=int(parsed.port),
                            username=username,
                            password_enc=password_enc,
                            enabled=1,
                            source=source,
                            source_ref=None,
                            updated_at=now,
                        )
                    )
                    created += 1
                    continue

                if conflict_policy == "overwrite":
                    existing.password_enc = password_enc
                    existing.enabled = 1
                    existing.source = source
                    existing.updated_at = now
                    updated += 1
                else:
                    skipped += 1

            await session.commit()

    await with_sqlite_busy_retry(_op)

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:200],
        "request_id": rid,
    }


@router.put("/proxies/endpoints/{endpoint_id}")
async def update_proxy_endpoint(
    endpoint_id: int,
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    if endpoint_id <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid endpoint id", status_code=400)

    rid = get_or_create_request_id(request)
    body = await _load_update_endpoint_json(request)
    enabled = bool(body["enabled"])

    now = iso_utc_ms()

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)
    async with Session() as session:
        row = await session.get(ProxyEndpoint, endpoint_id)
        if row is None:
            raise ApiError(code=ErrorCode.NOT_FOUND, message="Proxy endpoint not found", status_code=404)

        row.enabled = 1 if enabled else 0
        row.updated_at = now
        await session.commit()

    return {"ok": True, "endpoint_id": str(endpoint_id), "enabled": enabled, "request_id": rid}


@router.post("/proxies/easy-proxies/import")
async def import_easy_proxies(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)
    body = await _load_easy_import_json(request)

    base_url = str(body["base_url"])
    password = str(body["password"])
    conflict_policy = str(body["conflict_policy"])

    transport = getattr(request.app.state, "httpx_transport", None)

    try:
        bearer_token: str | None = None
        if password.strip():
            auth = await easy_proxies_auth(base_url=base_url, password=password, transport=transport)
            bearer_token = auth.token
        uris = await easy_proxies_export(base_url=base_url, bearer_token=bearer_token, transport=transport)
    except EasyProxiesError as exc:
        raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="easy_proxies import failed", status_code=502) from exc
    except Exception as exc:
        raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="easy_proxies import failed", status_code=502) from exc

    warnings: list[str] = []
    raw_count = len(uris)
    seen_keys: set[tuple[str, str, int, str]] = set()
    deduped: list[str] = []
    invalid_uris: list[str] = []
    duplicates = 0
    invalid = 0
    for raw in uris:
        uri = (raw or "").strip()
        if not uri:
            continue
        try:
            parsed = parse_proxy_uri(uri)
        except Exception:
            invalid += 1
            invalid_uris.append(uri)
            continue
        key = (str(parsed.scheme), str(parsed.host), int(parsed.port), str((parsed.username or "").strip()))
        if key in seen_keys:
            duplicates += 1
            continue
        seen_keys.add(key)
        deduped.append(uri)

    uris = deduped + invalid_uris
    if duplicates > 0:
        warnings.append(f"检测到导出结果包含重复入口（已去重 {duplicates} 条）。")
    if raw_count > 1 and len(uris) <= 1:
        warnings.append("当前 easy_proxies 可能处于 pool 模式（所有节点共享同一入口端口），导入后只会得到一个入口。若要每节点独立端口，请在 easy_proxies 启用 multi-port 或 hybrid 模式后再导入。")
    if invalid > 0:
        warnings.append(f"有 {invalid} 条导出内容不是合法代理 URI，已跳过。")

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    now = iso_utc_ms()

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    settings = request.app.state.settings
    encryptor: FieldEncryptor | None = None

    async def _op() -> None:
        nonlocal created, updated, skipped, errors, encryptor
        async with Session() as session:
            for uri in uris:
                try:
                    parsed = parse_proxy_uri(uri)
                except Exception:
                    errors.append({"code": "invalid_proxy_uri", "message": "invalid_proxy_uri"})
                    continue

                username = (parsed.username or "").strip()
                password_v = parsed.password
                password_enc = ""
                if password_v:
                    if encryptor is None:
                        try:
                            encryptor = FieldEncryptor.from_key(settings.field_encryption_key)
                        except Exception:
                            errors.append(
                                {
                                    "code": "encryption_not_configured",
                                    "message": "代理包含密码，但未配置加密密钥（FIELD_ENCRYPTION_KEY）",
                                }
                            )
                            continue
                    password_enc = encryptor.encrypt_text(password_v)

                existing = (
                    (
                        await session.execute(
                            sa.select(ProxyEndpoint).where(
                                ProxyEndpoint.scheme == parsed.scheme,
                                ProxyEndpoint.host == parsed.host,
                                ProxyEndpoint.port == int(parsed.port),
                                ProxyEndpoint.username == username,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )

                if existing is None:
                    session.add(
                        ProxyEndpoint(
                            scheme=parsed.scheme,
                            host=parsed.host,
                            port=int(parsed.port),
                            username=username,
                            password_enc=password_enc,
                            enabled=1,
                            source="easy_proxies",
                            source_ref=base_url,
                            updated_at=now,
                        )
                    )
                    created += 1
                    continue

                if conflict_policy == "skip_non_easy_proxies" and (existing.source or "") != "easy_proxies":
                    skipped += 1
                    continue
                if conflict_policy == "skip":
                    skipped += 1
                    continue

                existing.password_enc = password_enc
                existing.enabled = 1
                existing.source = "easy_proxies"
                existing.source_ref = base_url
                existing.updated_at = now
                updated += 1

            await session.commit()

    await with_sqlite_busy_retry(_op)

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:200],
        "warnings": warnings[:50],
        "request_id": rid,
    }


@router.post("/proxies/probe")
async def probe_proxies(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)
    opts = await _load_probe_json(request)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> int:
        async with Session() as session:
            job = JobRow(
                type="proxy_probe",
                status="pending",
                payload_json=json.dumps({"scope": "all", **opts}, ensure_ascii=False),
                ref_type="proxy_probe",
                ref_id="all",
            )
            session.add(job)
            await session.flush()
            await session.commit()
            return int(job.id)

    job_id = await with_sqlite_busy_retry(_op)

    return {"ok": True, "job_id": str(job_id), "request_id": rid}
