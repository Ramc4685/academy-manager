"""Every People CRM route is ``require_persona("admin")`` (spec §1, §7 Phase 4).

Walks the real admin router (reusing the owner-gate policy's walker) and
checks each ``/families`` route's dependency chain calls ``require_persona``
with ``"admin"``. Coaches get only a narrow safety card (spec §4), never a
family route; a CRM route added without the admin gate fails here.
"""

from __future__ import annotations

import inspect
from typing import Any

from backend.v2.tests.structural.test_owner_gate_policy import (
    _admin_app,
    _dependant_calls,
    _iter_routes,
)

_CRM_PREFIXES = ("/api/v2/admin/families",)


def _personas(route: Any) -> set[str]:
    found: set[str] = set()
    for call in _dependant_calls(route.dependant):
        if "require_persona" not in getattr(call, "__qualname__", ""):
            continue
        persona = inspect.getclosurevars(call).nonlocals.get("persona")
        if isinstance(persona, str):
            found.add(persona)
    return found


def _crm_routes() -> dict[tuple[str, str], Any]:
    routes: dict[tuple[str, str], Any] = {}
    for path, route in _iter_routes(_admin_app().routes):
        if not path.startswith(_CRM_PREFIXES) or not hasattr(route, "dependant"):
            continue
        for method in getattr(route, "methods", None) or ():
            if method != "HEAD":
                routes[(method, path)] = route
    return routes


def test_the_family_index_routes_are_registered() -> None:
    routes = _crm_routes()
    assert ("GET", "/api/v2/admin/families") in routes
    assert ("GET", "/api/v2/admin/families/summary") in routes


def test_every_crm_route_requires_the_admin_persona() -> None:
    ungated = sorted(key for key, route in _crm_routes().items() if "admin" not in _personas(route))
    assert not ungated, f"People CRM routes without require_persona('admin'): {ungated}"
