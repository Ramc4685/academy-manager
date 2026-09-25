"""An academy owner can no longer route its charges onto the platform account.

The platform-charge flag is derived from the house-academy setting; the admin
BFF keeps only the read.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from backend.v2.interfaces.admin.billing_routes import router


def _methods(path_suffix: str) -> set[str]:
    methods: set[str] = set()
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path.endswith(path_suffix):
            methods |= route.methods
    return methods


def test_platform_fallback_is_read_only() -> None:
    assert _methods("/billing/settings/platform-fallback") == {"GET"}
