"""Admin BFF router."""

from __future__ import annotations

from fastapi import APIRouter

from .billing_routes import router as billing_router
from .comms_routes import router as comms_router
from .sessions_routes import router as sessions_router
from .waitlist_routes import router as waitlist_router

router = APIRouter(prefix="/admin")
router.include_router(sessions_router)
router.include_router(waitlist_router)
router.include_router(billing_router)
router.include_router(comms_router)
