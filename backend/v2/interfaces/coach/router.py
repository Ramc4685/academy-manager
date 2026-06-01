"""Coach BFF router — composes today_routes + attendance_routes."""

from __future__ import annotations

from fastapi import APIRouter

from .attendance_routes import router as attendance_router
from .billing_enrollment_routes import router as billing_enrollment_router
from .dashboard_routes import router as dashboard_router
from .feedback_routes import router as feedback_router
from .notes_routes import router as notes_router
from .roster_routes import router as roster_router
from .today_routes import router as today_router

router = APIRouter(prefix="/coach")
router.include_router(today_router)
router.include_router(dashboard_router)
router.include_router(attendance_router)
router.include_router(notes_router)
router.include_router(roster_router)
router.include_router(feedback_router)
router.include_router(billing_enrollment_router)
