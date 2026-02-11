from __future__ import annotations

import time

from fastapi import FastAPI, Request

from app.api.admin.router import router as admin_router
from app.api.metrics import router as metrics_router
from app.api.public.healthz import router as healthz_router
from app.api.public.authors import router as authors_router
from app.api.public.images import router as images_router
from app.api.public.random import router as random_router
from app.api.public.tags import router as tags_router
from app.api.public.version import router as version_router
from app.core.config import load_settings
from app.core.errors import ApiError, json_error_response
from app.core.logging import configure_logging
from app.core.metrics import observe_random_result
from app.core.request_id import build_request_id_middleware
from app.db.engine import create_engine


def create_app() -> FastAPI:
    configure_logging()
    settings = load_settings()

    app = FastAPI(title="new-pixiv-api")

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):  # type: ignore[no-redef]
        return json_error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            request=request,
            details=exc.details,
        )

    request_id_middleware = build_request_id_middleware()
    if request_id_middleware is not None:
        app.add_middleware(request_id_middleware)

    def _random_result_from_status(status: int) -> str:
        if status in {200, 301, 302, 303, 307, 308}:
            return "ok"
        if status == 404:
            return "no_match"
        if status == 502:
            return "upstream_error"
        if status == 400:
            return "bad_request"
        return "error"

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):  # type: ignore[no-redef]
        if request.url.path != "/random":
            return await call_next(request)

        started = time.monotonic()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_s = time.monotonic() - started
            status_code = int(getattr(response, "status_code", 0) or 0)
            observe_random_result(result=_random_result_from_status(status_code), duration_s=duration_s)

    app.state.settings = settings
    app.state.engine = create_engine(settings.database_url)

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # type: ignore[no-redef]
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            await engine.dispose()

    app.include_router(healthz_router)
    app.include_router(authors_router)
    app.include_router(images_router)
    app.include_router(random_router)
    app.include_router(tags_router)
    app.include_router(version_router)
    app.include_router(metrics_router)
    app.include_router(admin_router)

    return app


app = create_app()
