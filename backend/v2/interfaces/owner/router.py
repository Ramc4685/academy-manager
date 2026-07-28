"""Aggregate owner route package. Mounted only when `enable_owner_role` is on."""

from __future__ import annotations

from fastapi import APIRouter

from backend.v2.interfaces.owner.rollup_routes import router as rollup_router

router = APIRouter(prefix="/owner")
router.include_router(rollup_router)
