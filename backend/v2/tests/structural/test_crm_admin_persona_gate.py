"""Every People CRM route is ``require_persona("admin")`` (spec §1, §7 Phase 4).

Walks the real admin router (reusing the owner-gate policy's walker) and
checks each ``/families`` route's dependency chain calls ``require_persona``
with ``"admin"``. Coaches get only a narrow safety card (spec §4), never a
family route; a CRM route added without the admin gate fails here.
"""

from __future__ import annotations

import inspect
from typing import Any

from backend.v2.interfaces.admin.owner_gate import OWNER_ONLY_ROUTE_PATHS
from backend.v2.tests.structural.test_owner_gate_policy import (
    _admin_app,
    _dependant_calls,
    _is_owner_guarded,
    _iter_routes,
)

_CRM_PREFIXES = ("/api/v2/admin/families", "/api/v2/admin/follow-ups")


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
    # Phase 4a: family notes and follow-ups.
    assert ("GET", "/api/v2/admin/families/{parent_id}/notes") in routes
    assert ("POST", "/api/v2/admin/families/{parent_id}/notes") in routes
    assert ("PATCH", "/api/v2/admin/families/{parent_id}/notes/{note_id}") in routes
    assert ("DELETE", "/api/v2/admin/families/{parent_id}/notes/{note_id}") in routes
    assert ("GET", "/api/v2/admin/families/{parent_id}/follow-ups") in routes
    assert ("POST", "/api/v2/admin/families/{parent_id}/follow-ups") in routes
    assert ("PATCH", "/api/v2/admin/families/{parent_id}/follow-ups/{follow_up_id}") in routes
    assert ("GET", "/api/v2/admin/follow-ups") in routes
    # Phase 4b: family contacts and family details.
    assert ("GET", "/api/v2/admin/families/{parent_id}/contacts") in routes
    assert ("POST", "/api/v2/admin/families/{parent_id}/contacts") in routes
    assert ("PATCH", "/api/v2/admin/families/{parent_id}/contacts/{contact_id}") in routes
    assert ("DELETE", "/api/v2/admin/families/{parent_id}/contacts/{contact_id}") in routes
    assert ("GET", "/api/v2/admin/families/{parent_id}/details") in routes
    assert ("PATCH", "/api/v2/admin/families/{parent_id}/details") in routes


def test_every_crm_route_requires_the_admin_persona() -> None:
    ungated = sorted(key for key, route in _crm_routes().items() if "admin" not in _personas(route))
    assert not ungated, f"People CRM routes without require_persona('admin'): {ungated}"


#: The family record page (Lane A4) calls these beyond ``/families``: the
#: child drawer's coach notes and its attendance Correct action (the #517
#: admin correction route). Every admin may use them; none is owner-only, and
#: none moves money, so none is in ``OWNER_ONLY_ROUTE_PATHS``.
_FAMILY_RECORD_ROUTES = (
    ("GET", "/api/v2/admin/families/{family_id}/record"),
    ("GET", "/api/v2/admin/families/{parent_id}/billing"),
    ("GET", "/api/v2/admin/students/{student_id}/coach-notes"),
    ("PATCH", "/api/v2/admin/session-occurrences/{occurrence_id}/attendance/{student_id}"),
)


def _all_admin_routes() -> dict[tuple[str, str], Any]:
    routes: dict[tuple[str, str], Any] = {}
    for path, route in _iter_routes(_admin_app().routes):
        if not hasattr(route, "dependant"):
            continue
        for method in getattr(route, "methods", None) or ():
            if method != "HEAD":
                routes[(method, path)] = route
    return routes


def test_family_record_routes_are_admin_gated_and_not_owner_only() -> None:
    routes = _all_admin_routes()
    for key in _FAMILY_RECORD_ROUTES:
        assert key in routes, f"family record route missing: {key}"
        route = routes[key]
        assert "admin" in _personas(route), f"{key} is not require_persona('admin')"
        assert not _is_owner_guarded(route), f"{key} must not be owner-only"
        assert key not in OWNER_ONLY_ROUTE_PATHS, f"{key} is listed as owner-only"
