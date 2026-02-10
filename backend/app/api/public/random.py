from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.errors import ApiError, ErrorCode
from app.core.http_stream import stream_url
from app.db.random_pick import pick_random_image
from app.db.session import create_sessionmaker

router = APIRouter()


@router.get("/random")
async def random_image(
    request: Request,
    format: str = "image",
) -> Any:
    if format != "image":
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported format", status_code=400)

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)

    async with Session() as session:
        image = await pick_random_image(session, r=random.random())
        if image is None:
            raise ApiError(code=ErrorCode.NO_MATCH, message="No matching image.", status_code=404)

    transport = getattr(request.app.state, "httpx_transport", None)
    return await stream_url(
        image.original_url,
        transport=transport,
        cache_control="no-store",
    )

