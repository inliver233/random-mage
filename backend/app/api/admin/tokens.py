from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request

from app.api.admin.deps import get_admin_claims
from app.core.request_id import get_or_create_request_id
from app.db.models.pixiv_tokens import PixivToken
from app.db.session import create_sessionmaker

router = APIRouter()


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
