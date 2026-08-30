"""Coach BFF router — composes today_routes + attendance_routes."""

from __future__ import annotations

from fastapi import APIRouter

from .attendance_routes import router as attendance_router
from .billing_enrollment_routes import router as billing_enrollment_router
from .dashboard_routes import router as dashboard_router
from .feedback_routes import router as feedback_router
from .messages_routes import router as messages_router
from .notes_routes import router as notes_router
from .profile_routes import router as profile_router
from .roster_routes import router as roster_router
from .sessions_routes import router as sessions_router
from .skill_routes import router as skill_router
from .teaching_plan_routes import router as teaching_plan_router
from .today_routes import router as today_router

router = APIRouter(prefix="/coach")
router.include_router(today_router)
router.include_router(teaching_plan_router)
router.include_router(sessions_router)
router.include_router(profile_router)
router.include_router(dashboard_router)
router.include_router(attendance_router)
router.include_router(notes_router)
router.include_router(roster_router)
router.include_router(feedback_router)
router.include_router(billing_enrollment_router)
router.include_router(skill_router)
router.include_router(messages_router)
