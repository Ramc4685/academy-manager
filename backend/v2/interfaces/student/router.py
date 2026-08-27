"""Student BFF router (UIM12)."""

from __future__ import annotations

from fastapi import APIRouter

from .me_routes import router as me_router
from .progress_routes import router as progress_router
from .schedule_routes import router as schedule_router

router = APIRouter(prefix="/student")
router.include_router(me_router)
router.include_router(progress_router)
router.include_router(schedule_router)
