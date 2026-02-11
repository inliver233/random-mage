from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.crypto import FieldEncryptor, mask_secret
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_or_create_request_id
from app.db.models.pixiv_tokens import PixivToken
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


async def _load_create_token_json(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400) from exc

    if not isinstance(data, dict):
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Invalid JSON body", status_code=400)

    refresh_token = str(data.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Missing refresh_token", status_code=400)
    if len(refresh_token) > 2048:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported refresh_token", status_code=400)

    label_raw = data.get("label")
    label = str(label_raw).strip() if label_raw is not None else None
    label = label if label else None

    enabled = _parse_bool(data.get("enabled"), default=True)

    weight_raw = data.get("weight", 1.0)
    try:
        weight = float(weight_raw)
    except Exception as exc:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported weight", status_code=400) from exc
    if weight < 0.0 or weight > 100.0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported weight", status_code=400)

    return {
        "label": label,
        "enabled": enabled,
        "weight": weight,
        "refresh_token": refresh_token,
    }


@router.get("/tokens")
async def list_tokens(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async with Session() as session:
        tokens = (
            (
                await session.execute(
                    sa.select(PixivToken).order_by(PixivToken.id.desc())
                )
            )
            .scalars()
            .all()
        )

    items = [
        {
            "id": str(t.id),
            "label": t.label,
            "enabled": bool(t.enabled),
            "weight": float(t.weight),
            "error_count": int(t.error_count or 0),
            "backoff_until": t.backoff_until,
            "last_ok_at": t.last_ok_at,
            "last_fail_at": t.last_fail_at,
            "last_error_code": t.last_error_code,
            "last_error_msg": t.last_error_msg,
        }
        for t in tokens
    ]

    return {"ok": True, "items": items, "request_id": rid}


@router.post("/tokens")
async def create_token(
    request: Request,
    _claims: dict[str, Any] = Depends(get_admin_claims),
) -> dict[str, Any]:
    _ = _claims
    rid = get_or_create_request_id(request)
    body = await _load_create_token_json(request)

    settings = request.app.state.settings
    try:
        encryptor = FieldEncryptor.from_key(settings.field_encryption_key)
    except Exception as exc:
        raise ApiError(code=ErrorCode.INTERNAL_ERROR, message="Encryption not configured", status_code=500) from exc

    refresh_token = str(body["refresh_token"])
    refresh_token_enc = encryptor.encrypt_text(refresh_token)
    refresh_token_masked = mask_secret(refresh_token)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)
    async with Session() as session:
        row = PixivToken(
            label=body["label"],
            enabled=1 if bool(body["enabled"]) else 0,
            refresh_token_enc=refresh_token_enc,
            refresh_token_masked=refresh_token_masked,
            weight=float(body["weight"]),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return {"ok": True, "token_id": str(row.id), "request_id": rid}
