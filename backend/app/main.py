from __future__ import annotations

import time

from fastapi import FastAPI, Request

from app.api.admin.router import router as admin_router
from app.api.metrics import router as metrics_router
from app.api.public.healthz import router as healthz_router
from app.api.public.authors import router as authors_router
from app.api.public.images import router as images_router
from app.api.public.legacy import router as legacy_router
from app.api.public.random import router as random_router
from app.api.public.tags import router as tags_router
from app.api.public.version import router as version_router
from app.core.config import load_settings
from app.core.api_keys import ApiKeyAuthConfig, ApiKeyAuthenticator, ApiKeyRateLimiter, require_public_api_key
from app.core.errors import ApiError, json_error_response
from app.core.logging import configure_logging
from app.core.metrics import observe_random_result
from app.core.request_id import build_request_id_middleware, get_or_create_request_id, set_request_id_on_state
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

    engine = create_engine(settings.database_url)
    app.state.engine = engine

    api_key_cfg = ApiKeyAuthConfig(
        required=bool(settings.public_api_key_required),
        rpm=int(settings.public_api_key_rpm),
        burst=int(settings.public_api_key_burst),
        secret_key=str(settings.secret_key),
    )
    app.state.api_key_authenticator = ApiKeyAuthenticator(engine, api_key_cfg)
    app.state.api_key_limiter = ApiKeyRateLimiter(rpm=int(api_key_cfg.rpm), burst=int(api_key_cfg.burst))

    @app.middleware("http")
    async def _public_api_key_middleware(request: Request, call_next):  # type: ignore[no-redef]
        if not bool(settings.public_api_key_required):
            return await call_next(request)

        path = request.url.path
        if path.startswith("/admin") or path.startswith("/metrics"):
            return await call_next(request)
        if path in {"/healthz", "/version", "/openapi.json", "/docs", "/redoc"}:
            return await call_next(request)

        rid = get_or_create_request_id(request)
        set_request_id_on_state(request, rid)

        try:
            api_key_id = await require_public_api_key(
                request.app.state.api_key_authenticator,
                request.app.state.api_key_limiter,
                headers=request.headers,
            )
        except ApiError as exc:
            return json_error_response(
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                request=request,
                details=exc.details,
            )
        request.state.api_key_id = int(api_key_id)

        return await call_next(request)

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

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # type: ignore[no-redef]
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            await engine.dispose()

    app.include_router(healthz_router)
    app.include_router(authors_router)
    app.include_router(images_router)
    app.include_router(legacy_router)
    app.include_router(random_router)
    app.include_router(tags_router)
    app.include_router(version_router)
    app.include_router(metrics_router)
    app.include_router(admin_router)

    return app


app = create_app()
