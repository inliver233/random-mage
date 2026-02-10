from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.core.errors import ApiError, ErrorCode
from app.core.http_stream import stream_url
from app.core.runtime_settings import load_runtime_config
from app.db.random_pick import pick_random_image
from app.db.session import create_sessionmaker

router = APIRouter()


@router.get("/random")
async def random_image(
    request: Request,
    format: str = "image",
    redirect: int = 0,
) -> Any:
    if format not in {"image", "json"}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported format", status_code=400)
    if redirect not in {0, 1}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported redirect", status_code=400)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async with Session() as session:
        image = await pick_random_image(session, r=random.random())
        if image is None:
            raise ApiError(code=ErrorCode.NO_MATCH, message="No matching image.", status_code=404)

    if format == "image" and redirect == 1:
        return RedirectResponse(
            url=f"/i/{image.id}.{image.ext}",
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    if format == "json":
        runtime = await load_runtime_config(engine)
        origin_url = None if runtime.hide_origin_url_in_public_json else image.original_url

        return {
            "ok": True,
            "code": "OK",
            "request_id": getattr(getattr(request, "state", None), "request_id", None) or "req_unknown",
            "data": {
                "image": {
                    "id": str(image.id),
                    "illust_id": str(image.illust_id),
                    "page_index": image.page_index,
                    "ext": image.ext,
                    "width": image.width,
                    "height": image.height,
                    "x_restrict": image.x_restrict,
                    "ai_type": image.ai_type,
                    "user": {
                        "id": str(image.user_id) if image.user_id is not None else None,
                        "name": image.user_name,
                    },
                    "title": image.title,
                    "created_at_pixiv": image.created_at_pixiv,
                },
                "tags": [],
                "urls": {
                    "proxy": f"/i/{image.id}.{image.ext}",
                    "origin": origin_url,
                    "legacy_single": f"/{image.illust_id}.{image.ext}",
                    "legacy_multi": f"/{image.illust_id}-{image.page_index + 1}.{image.ext}",
                },
                "debug": {
                    "attempts_used": 1,
                    "picked_by": "random_key",
                },
            },
        }

    transport = getattr(request.app.state, "httpx_transport", None)
    return await stream_url(
        image.original_url,
        transport=transport,
        cache_control="no-store",
        range_header=request.headers.get("Range"),
    )
