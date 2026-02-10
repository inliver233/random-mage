from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.errors import ApiError, ErrorCode
from app.core.http_stream import stream_url
from app.core.runtime_settings import load_runtime_config
from app.db.tags_get import get_tag_names_for_image
from app.db.random_pick import pick_random_image
from app.db.session import create_sessionmaker

router = APIRouter()

_MAX_TAG_FILTERS = 50


@router.get("/random")
async def random_image(
    request: Request,
    format: str = "image",
    redirect: int = 0,
    r18: int = 0,
    r18_strict: int = 1,
    orientation: str = "any",
    min_width: int = 0,
    min_height: int = 0,
    min_pixels: int = 0,
    included_tags: list[str] | None = Query(default=None),
    excluded_tags: list[str] | None = Query(default=None),
    user_id: int | None = None,
    illust_id: int | None = None,
) -> Any:
    if format not in {"image", "json"}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported format", status_code=400)
    if redirect not in {0, 1}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported redirect", status_code=400)
    if r18 not in {0, 1, 2}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported r18", status_code=400)
    if r18_strict not in {0, 1}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported r18_strict", status_code=400)
    orientation = (orientation or "").strip().lower()
    orientation_map = {"any": None, "portrait": 1, "landscape": 2, "square": 3}
    if orientation not in orientation_map:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported orientation", status_code=400)
    if min_width < 0 or min_height < 0 or min_pixels < 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported min_*", status_code=400)

    def _parse_tags(values: list[str] | None) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values or []:
            for part in str(raw).split("|"):
                name = part.strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(name)
        return out

    included = _parse_tags(included_tags)
    excluded = _parse_tags(excluded_tags)
    if len(included) > _MAX_TAG_FILTERS or len(excluded) > _MAX_TAG_FILTERS:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Too many tag filters", status_code=400)
    if user_id is not None and int(user_id) <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported user_id", status_code=400)
    if illust_id is not None and int(illust_id) <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported illust_id", status_code=400)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    tags: list[str] = []
    async with Session() as session:
        image = await pick_random_image(
            session,
            r=random.random(),
            r18=r18,
            r18_strict=bool(r18_strict),
            orientation=orientation_map[orientation],
            min_width=min_width,
            min_height=min_height,
            min_pixels=min_pixels,
            included_tags=included,
            excluded_tags=excluded,
            user_id=user_id,
            illust_id=illust_id,
        )
        if image is None:
            raise ApiError(code=ErrorCode.NO_MATCH, message="No matching image.", status_code=404)
        if format == "json":
            tags = await get_tag_names_for_image(session, image_id=image.id)

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
                "tags": tags,
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
