from __future__ import annotations

import json
from typing import Any

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
            "enabled": bool(p.enabled),
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
                if p.blacklisted_until
                else "ok"
                if p.last_ok_at and (not p.last_fail_at or str(p.last_ok_at) >= str(p.last_fail_at))
                else "fail"
                if p.last_fail_at
                else "unknown"
            ),
            "blacklisted_until": p.blacklisted_until,
            "last_error": p.last_error,
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
    if not password:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing password", status_code=400)

    conflict_policy = _parse_easy_conflict_policy(data.get("conflict_policy"))
    return {"base_url": base_url, "password": password, "conflict_policy": conflict_policy}


@router.post("/proxies/endpoints/import")
async def import_proxy_endpoints(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    body = await _load_import_json(request)

    settings = request.app.state.settings
    try:
        encryptor = FieldEncryptor.from_key(settings.field_encryption_key)
    except Exception as exc:
        raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="Encryption not configured", status_code=500) from exc

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

    async def _op() -> None:
        nonlocal created, updated, skipped, errors
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
                password_enc = encryptor.encrypt_text(password) if password else ""

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


@router.post("/proxies/easy-proxies/import")
async def import_easy_proxies(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)
    body = await _load_easy_import_json(request)

    settings = request.app.state.settings
    try:
        encryptor = FieldEncryptor.from_key(settings.field_encryption_key)
    except Exception as exc:
        raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="Encryption not configured", status_code=500) from exc

    base_url = str(body["base_url"])
    password = str(body["password"])
    conflict_policy = str(body["conflict_policy"])

    transport = getattr(request.app.state, "httpx_transport", None)

    try:
        auth = await easy_proxies_auth(base_url=base_url, password=password, transport=transport)
        uris = await easy_proxies_export(base_url=base_url, bearer_token=auth.token, transport=transport)
    except EasyProxiesError as exc:
        raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="easy_proxies import failed", status_code=502) from exc
    except Exception as exc:
        raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="easy_proxies import failed", status_code=502) from exc

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    now = iso_utc_ms()

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> None:
        nonlocal created, updated, skipped, errors
        async with Session() as session:
            for uri in uris:
                uri = (uri or "").strip()
                if not uri:
                    continue
                try:
                    parsed = parse_proxy_uri(uri)
                except Exception:
                    errors.append({"code": "invalid_proxy_uri", "message": "invalid_proxy_uri"})
                    continue

                username = (parsed.username or "").strip()
                password_v = parsed.password
                password_enc = encryptor.encrypt_text(password_v) if password_v else ""

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
        "request_id": rid,
    }


@router.post("/proxies/probe")
async def probe_proxies(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async def _op() -> int:
        async with Session() as session:
            job = JobRow(
                type="proxy_probe",
                status="pending",
                payload_json=json.dumps({"scope": "all"}, ensure_ascii=False),
                ref_type="proxy_probe",
                ref_id="all",
            )
            session.add(job)
            await session.flush()
            await session.commit()
            return int(job.id)

    job_id = await with_sqlite_busy_retry(_op)

    return {"ok": True, "job_id": str(job_id), "request_id": rid}
