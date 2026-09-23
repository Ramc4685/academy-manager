"""Aggregate router for the anonymous ``/api/v2/public/*`` persona."""

from __future__ import annotations

from fastapi import APIRouter

from backend.v2.interfaces.public.academy_page_routes import router as academy_page_router

router = APIRouter(prefix="/public", tags=["public"])
router.include_router(academy_page_router)
