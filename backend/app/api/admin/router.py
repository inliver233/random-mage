from __future__ import annotations

from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.imports import router as imports_router
from app.api.admin.tokens import router as tokens_router

router = APIRouter(prefix="/admin/api")
router.include_router(auth_router)
router.include_router(imports_router)
router.include_router(tokens_router)
