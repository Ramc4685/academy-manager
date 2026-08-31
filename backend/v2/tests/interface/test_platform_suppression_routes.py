"""The suppression list is cross-tenant, so its surface is platform-only (#556).

The first cut of this endpoint hung off the admin router behind
``require_persona("admin")``. Because the suppression store is keyed on the
email address alone and holds every academy's addresses, that handed any single
tenant's admin the email addresses of every other academy's parents and coaches
— together with the fact that a named person filed a spam complaint — and let
them release another tenant's hard bounce. ``shared/auth/claims.py`` states the
rule being broken: academy-scoped ``roles`` must never gate cross-tenant data.

These tests pin the guard. They are written against the claims, not the route
path, so moving the router again cannot quietly re-open the hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.communications.domain.email_suppression import (
    EmailSuppression,
    SuppressionReason,
)
from backend.v2.interfaces.platform.suppression_routes import (
    router as suppression_router,
)
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _platform_admin() -> AuthClaims:
    return AuthClaims(
        user_id="platform-admin",
        email="ops@example.com",
        academy_id="platform-control",
        platform_roles=("platform_admin",),
    )


def _platform_support() -> AuthClaims:
    return AuthClaims(
        user_id="platform-support",
        email="support@example.com",
        academy_id="platform-control",
        platform_roles=("platform_support",),
    )


def _academy_admin() -> AuthClaims:
    """An ordinary tenant admin — the persona the first cut wrongly allowed."""
    return AuthClaims(
        user_id="academy-admin",
        email="admin@academy-a.example.com",
        academy_id="acad_a",
        membership_id="membership_admin",
        roles=("admin",),
    )


@dataclass
class _FakeList:
    async def execute(self, *, limit: int = 100) -> list[EmailSuppression]:
        now = datetime.now(UTC)
        return [
            EmailSuppression(
                email="parent@academy-b.example.com",
                reason=SuppressionReason.COMPLAINT,
                bounce_subtype=None,
                provider="resend",
                first_seen_at=now,
                last_seen_at=now,
                active=True,
            )
        ]


@dataclass
class _FakeRelease:
    released: list[tuple[str, str]]

    async def execute(self, *, email: str, released_by: str) -> bool:
        self.released.append((email, released_by))
        return True


def _client(claims: AuthClaims) -> tuple[TestClient, list[tuple[str, str]]]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(suppression_router, prefix="/api/v2")
    released: list[tuple[str, str]] = []
    app.state.list_email_suppressions = _FakeList()
    app.state.release_email_suppression = _FakeRelease(released)

    async def _override() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override
    return TestClient(app), released


LIST_URL = "/api/v2/platform/communications/suppressions"
RELEASE_URL = "/api/v2/platform/communications/suppressions/parent@academy-b.example.com/release"


@pytest.mark.parametrize("claims_factory", [_platform_admin, _platform_support])
def test_platform_operators_can_read_the_list(claims_factory) -> None:
    client, _ = _client(claims_factory())

    response = client.get(LIST_URL)

    assert response.status_code == 200
    rows = response.json()["suppressions"]
    assert [row["email"] for row in rows] == ["parent@academy-b.example.com"]


def test_a_tenant_admin_cannot_read_another_academys_suppressions() -> None:
    """The whole point of the move: academy `admin` is not a platform role."""
    client, _ = _client(_academy_admin())

    response = client.get(LIST_URL)

    assert response.status_code == 404
    assert "parent@academy-b.example.com" not in response.text


def test_a_tenant_admin_cannot_release_another_academys_suppression() -> None:
    client, released = _client(_academy_admin())

    response = client.post(RELEASE_URL)

    assert response.status_code == 404
    assert released == [], "a tenant admin must not reach the release use case at all"


def test_platform_admin_can_release() -> None:
    client, released = _client(_platform_admin())

    response = client.post(RELEASE_URL)

    assert response.status_code == 200
    assert response.json() == {"released": True}
    assert released == [("parent@academy-b.example.com", "platform-admin")]


def test_release_is_admin_only_not_support() -> None:
    """Reading the list is support-visible; mutating it is not."""
    client, released = _client(_platform_support())

    response = client.post(RELEASE_URL)

    assert response.status_code == 404
    assert released == []
