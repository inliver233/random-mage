from __future__ import annotations

from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.bindings import router as bindings_router
from app.api.admin.imports import router as imports_router
from app.api.admin.jobs import router as jobs_router
from app.api.admin.proxies import router as proxies_router
from app.api.admin.proxy_pools import router as proxy_pools_router
from app.api.admin.tokens import router as tokens_router

router = APIRouter(prefix="/admin/api")
router.include_router(auth_router)
router.include_router(bindings_router)
router.include_router(imports_router)
router.include_router(jobs_router)
router.include_router(proxies_router)
router.include_router(proxy_pools_router)
router.include_router(tokens_router)
