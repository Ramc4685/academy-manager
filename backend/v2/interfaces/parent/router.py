"""Parent BFF router."""

from __future__ import annotations

from fastapi import APIRouter

from .activity_routes import router as activity_router
from .invoice_routes import router as invoice_router
from .onboarding_routes import router as onboarding_router
from .pause_routes import router as pause_router
from .payment_routes import router as payment_router
from .schedule_routes import router as schedule_router
from .session_routes import router as session_router
from .webhook_routes import router as webhook_router

router = APIRouter(prefix="/parent")
router.include_router(activity_router)
router.include_router(invoice_router)
router.include_router(onboarding_router)
router.include_router(pause_router)
router.include_router(payment_router)
router.include_router(schedule_router)
router.include_router(session_router)
router.include_router(webhook_router)
