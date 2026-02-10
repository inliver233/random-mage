from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.errors import ApiError, ErrorCode
from app.core.http_stream import stream_url
from app.core.pixiv_urls import ALLOWED_IMAGE_EXTS
from app.db.images_get import get_image_by_id
from app.db.session import create_sessionmaker

router = APIRouter()


@router.get("/i/{image_id}.{ext}")
async def proxy_image(
    request: Request,
    image_id: int,
    ext: str,
):
    ext = (ext or "").lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported ext", status_code=400)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async with Session() as session:
        image = await get_image_by_id(session, image_id=image_id)
        if image is None or (image.ext or "").lower() != ext:
            raise ApiError(code=ErrorCode.NOT_FOUND, message="Image not found", status_code=404)

    transport = getattr(request.app.state, "httpx_transport", None)
    return await stream_url(
        image.original_url,
        transport=transport,
        cache_control="no-store",
    )

