"""Admin BFF router."""

from __future__ import annotations

from fastapi import APIRouter

from .academy_routes import router as academy_router
from .audit_routes import router as audit_router
from .billing_routes import router as billing_router
from .coach_pay_rate_routes import router as coach_pay_rate_router
from .comms_routes import router as comms_router
from .dashboard_routes import router as dashboard_router
from .directory_routes import router as directory_router
from .dues_routes import router as dues_router
from .pathway_routes import router as pathway_router
from .pause_routes import router as pause_router
from .payout_period_routes import router as payout_period_router
from .payroll_routes import router as payroll_router
from .progress_routes import router as progress_router
from .registration_routes import router as registration_router
from .reports_routes import router as reports_router
from .session_type_routes import router as session_type_router
from .sessions_routes import router as sessions_router
from .teaching_plan_routes import router as teaching_plan_router
from .waitlist_routes import router as waitlist_router
from .waiver_routes import router as waiver_router

router = APIRouter(prefix="/admin")
router.include_router(audit_router)
router.include_router(dashboard_router)
router.include_router(directory_router)
router.include_router(pause_router)
router.include_router(registration_router)
router.include_router(dues_router)
router.include_router(reports_router)
router.include_router(sessions_router)
router.include_router(teaching_plan_router)
router.include_router(session_type_router)
router.include_router(waitlist_router)
router.include_router(billing_router)
router.include_router(payout_period_router)
router.include_router(payroll_router)
router.include_router(coach_pay_rate_router)
router.include_router(comms_router)
router.include_router(academy_router)
router.include_router(waiver_router)
router.include_router(pathway_router)
router.include_router(progress_router)
