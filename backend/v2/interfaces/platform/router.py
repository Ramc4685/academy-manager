"""Aggregate platform route package.

Wave 8 agents own separate platform slices. Keep this router as the single
mount point so each slice can add its router without repeatedly editing
``backend.v2.main``.
"""

from __future__ import annotations

from importlib import import_module

from fastapi import APIRouter

from backend.v2.interfaces.platform.bootstrap_routes import router as bootstrap_router

router = APIRouter()
router.include_router(bootstrap_router)


def _include_if_available(module_name: str, router_name: str = "router") -> None:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return
    child_router = getattr(module, router_name, None)
    if child_router is not None:
        router.include_router(child_router)


_include_if_available("backend.v2.interfaces.platform.billing_routes")
_include_if_available("backend.v2.interfaces.platform.governance_routes")
_include_if_available("backend.v2.interfaces.platform.audit_routes")
_include_if_available("backend.v2.interfaces.platform.connect_routes")
