"""Coach BFF router — composes today_routes + attendance_routes."""

from __future__ import annotations

from fastapi import APIRouter

from .attendance_routes import router as attendance_router
from .today_routes import router as today_router

router = APIRouter(prefix="/coach")
router.include_router(today_router)
router.include_router(attendance_router)
