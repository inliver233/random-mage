from __future__ import annotations

from fastapi import APIRouter

from app.api.admin.imports import router as imports_router

router = APIRouter(prefix="/admin/api")
router.include_router(imports_router)

