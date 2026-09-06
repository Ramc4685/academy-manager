"""The owner/admin split is declared once and enforced everywhere.

``OWNER_ONLY_ROUTE_PATHS`` (``interfaces/admin/owner_gate.py``) is the single
source of truth for which admin routes need the ``owner`` role. This test
walks the real admin router and checks the dependency chain agrees with that
set in BOTH directions: every listed route is guarded by ``require_owner`` and
no unlisted route is. A route moved onto the wrong side of the line fails
here, not in production.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI

from backend.v2.interfaces.admin.owner_gate import OWNER_ONLY_ROUTE_PATHS
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.tests._route_paths import route_paths

_ADMIN_PREFIX = "/api/v2/admin"


def _iter_routes(routes: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield ``(full_path, route)`` for every concrete route.

    Mirrors ``tests/_route_paths.iter_route_paths`` but keeps the route object
    so its ``dependant`` can be inspected (FastAPI >= 0.139 keeps mounted
    routers as ``_IncludedRouter`` wrappers instead of copying routes up).
    """
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            include_context = getattr(route, "include_context", None)
            sub_prefix = prefix + (getattr(include_context, "prefix", "") or "")
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from _iter_routes(original.routes, sub_prefix)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path, route


def _dependant_calls(dependant: Any) -> Iterator[Any]:
    """Every callable in a route's dependency tree, depth first."""
    call = getattr(dependant, "call", None)
    if call is not None:
        yield call
    for sub in getattr(dependant, "dependencies", ()) or ():
        yield from _dependant_calls(sub)


def _is_owner_guarded(route: Any) -> bool:
    return any(
        "require_owner" in getattr(call, "__qualname__", "")
        for call in _dependant_calls(route.dependant)
    )


def _admin_app() -> FastAPI:
    # Exactly how main.py mounts it: `app.include_router(admin_router, prefix="/api/v2")`.
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v2")
    return app


def _admin_routes() -> dict[tuple[str, str], Any]:
    routes: dict[tuple[str, str], Any] = {}
    for path, route in _iter_routes(_admin_app().routes):
        if not path.startswith(_ADMIN_PREFIX):
            continue
        for method in getattr(route, "methods", None) or ():
            if method == "HEAD":
                continue
            routes[(method, path)] = route
    return routes


def test_owner_only_set_is_non_empty_and_names_the_refund_route() -> None:
    assert OWNER_ONLY_ROUTE_PATHS
    assert ("POST", f"{_ADMIN_PREFIX}/payments/refund") in OWNER_ONLY_ROUTE_PATHS


def test_every_owner_only_route_exists_on_the_real_router() -> None:
    registered = _admin_routes()
    missing = sorted(key for key in OWNER_ONLY_ROUTE_PATHS if key not in registered)
    assert not missing, f"listed as owner-only but not registered: {missing}"


def test_every_owner_only_route_is_guarded_by_require_owner() -> None:
    registered = _admin_routes()
    unguarded = sorted(
        key
        for key in OWNER_ONLY_ROUTE_PATHS
        if key in registered and not _is_owner_guarded(registered[key])
    )
    assert not unguarded, f"listed as owner-only but not behind require_owner: {unguarded}"


def test_no_other_admin_route_is_guarded_by_require_owner() -> None:
    registered = _admin_routes()
    stray = sorted(
        key
        for key, route in registered.items()
        if key not in OWNER_ONLY_ROUTE_PATHS and _is_owner_guarded(route)
    )
    assert not stray, f"behind require_owner but missing from OWNER_ONLY_ROUTE_PATHS: {stray}"


def test_route_paths_helper_sees_the_same_admin_surface() -> None:
    """Guard against the walker above silently diverging from the shared helper."""
    app = _admin_app()
    assert {path for path, _ in _iter_routes(app.routes)} == route_paths(app)
