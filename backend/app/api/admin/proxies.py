from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.crypto import FieldEncryptor
from app.core.errors import ApiError, ErrorCode
from app.core.proxy_uri import parse_proxy_uri
from app.core.request_id import get_or_create_request_id
from app.core.time import iso_utc_ms
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.session import create_sessionmaker, with_sqlite_busy_retry

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


def _parse_conflict_policy(value: Any) -> str:
    v = str(value or "").strip().lower() or "skip"
    if v not in {"skip", "overwrite"}:
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
