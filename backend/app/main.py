from __future__ import annotations

from fastapi import FastAPI

from app.api.public.healthz import router as healthz_router
from app.core.config import load_settings
from app.core.logging import configure_logging
from app.core.request_id import build_request_id_middleware
from app.db.engine import create_engine


def create_app() -> FastAPI:
    configure_logging()
    settings = load_settings()

    app = FastAPI(title="new-pixiv-api")

    request_id_middleware = build_request_id_middleware()
    if request_id_middleware is not None:
        app.add_middleware(request_id_middleware)

    app.state.settings = settings
    app.state.engine = create_engine(settings.database_url)

    app.include_router(healthz_router)

    return app


app = create_app()
