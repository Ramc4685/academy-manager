"""Coach BFF router — composes today_routes + attendance_routes.

There is deliberately NO billing router here. Owner decision 2026-09-12
(issue #774): a coach sees exactly one thing about money — the
"PAYMENT DUE $X" chip on the roster row — so they can tell the parent.
The proration-preview routes this used to mount were removed with it.
"""

from __future__ import annotations

from fastapi import APIRouter

from .announcement_routes import router as announcement_router
from .attendance_routes import router as attendance_router
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
router.include_router(skill_router)
router.include_router(messages_router)
router.include_router(announcement_router)
