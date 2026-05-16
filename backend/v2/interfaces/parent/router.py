"""Parent BFF router."""

from __future__ import annotations

from fastapi import APIRouter

from .onboarding_routes import router as onboarding_router
from .payment_routes import router as payment_router
from .webhook_routes import router as webhook_router

router = APIRouter(prefix="/parent")
router.include_router(onboarding_router)
router.include_router(payment_router)
router.include_router(webhook_router)
