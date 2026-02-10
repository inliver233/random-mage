from __future__ import annotations

import asyncio

import httpx

from app.core.http_stream import PIXIV_REFERER, stream_url


class _DummyStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def test_stream_url_uses_streaming(monkeypatch) -> None:
    sent_stream_flag: bool | None = None
    dummy_stream = _DummyStream([b"abc", b"def"])

    async def fake_send(self, request: httpx.Request, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal sent_stream_flag
        sent_stream_flag = bool(kwargs.get("stream"))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/octet-stream"},
            stream=dummy_stream,
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send, raising=True)

    async def _run() -> bytes:
        resp = await stream_url("https://example.test/big.bin", cache_control="no-store")
        chunks: list[bytes] = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        if resp.background is not None:
            await resp.background()
        return b"".join(chunks)

    body = asyncio.run(_run())
    assert sent_stream_flag is True
    assert body == b"abcdef"
    assert dummy_stream.closed is True


def test_stream_url_sets_pixiv_referer_header_by_default(monkeypatch) -> None:
    seen_referer: str | None = None
    dummy_stream = _DummyStream([b"x"])

    async def fake_send(self, request: httpx.Request, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal seen_referer
        seen_referer = request.headers.get("Referer")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/octet-stream"},
            stream=dummy_stream,
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send, raising=True)

    async def _run() -> None:
        resp = await stream_url("https://example.test/x.bin", cache_control="no-store")
        async for _ in resp.body_iterator:
            pass
        if resp.background is not None:
            await resp.background()

    asyncio.run(_run())
    assert seen_referer == PIXIV_REFERER
