from __future__ import annotations

from typing import Any

import httpx
from starlette.responses import StreamingResponse

from app.core.errors import ApiError, ErrorCode

PIXIV_REFERER = "https://www.pixiv.net/"


async def stream_url(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
    cache_control: str,
    referer: str = PIXIV_REFERER,
    timeout_s: float = 30.0,
) -> StreamingResponse:
    client = httpx.AsyncClient(
        transport=transport,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_s, connect=10.0),
    )

    request_headers = {"Referer": referer} if referer else {}
    request = client.build_request("GET", url, headers=request_headers)

    try:
        upstream = await client.send(request, stream=True)
    except Exception as exc:
        await client.aclose()
        raise ApiError(code=ErrorCode.UPSTREAM_STREAM_ERROR, message="Upstream request failed", status_code=502) from exc

    if upstream.status_code != 200:
        status = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        if status == 403:
            raise ApiError(code=ErrorCode.UPSTREAM_403, message="Upstream forbidden", status_code=502)
        if status == 404:
            raise ApiError(code=ErrorCode.UPSTREAM_404, message="Upstream not found", status_code=502)
        raise ApiError(code=ErrorCode.UPSTREAM_STREAM_ERROR, message="Upstream error", status_code=502)

    media_type = upstream.headers.get("content-type") or "application/octet-stream"
    content_length = upstream.headers.get("content-length")

    async def _iter_bytes() -> Any:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    resp = StreamingResponse(_iter_bytes(), status_code=200, media_type=media_type)
    resp.headers["Cache-Control"] = cache_control
    if content_length:
        resp.headers["Content-Length"] = content_length
    return resp
