"""Admin BFF router."""

from __future__ import annotations

from fastapi import APIRouter

from .audit_routes import router as audit_router
from .billing_routes import router as billing_router
from .comms_routes import router as comms_router
from .directory_routes import router as directory_router
from .dues_routes import router as dues_router
from .pause_routes import router as pause_router
from .reports_routes import router as reports_router
from .sessions_routes import router as sessions_router
from .waiver_routes import router as waiver_router
from .waitlist_routes import router as waitlist_router
from .academy_routes import router as academy_router

router = APIRouter(prefix="/admin")
router.include_router(audit_router)
router.include_router(directory_router)
router.include_router(pause_router)
router.include_router(dues_router)
router.include_router(reports_router)
router.include_router(sessions_router)
router.include_router(waitlist_router)
router.include_router(billing_router)
router.include_router(comms_router)
router.include_router(academy_router)
router.include_router(waiver_router)
