"""``assistant_coach`` role plumbing that has no route of its own."""

from __future__ import annotations

from typing import get_args

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.domain import models as identity_models
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import (
    _ROLE_PRIVILEGE,
    _lowers_privilege,
)
from backend.v2.shared.auth import claims as auth_claims
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http.persona import (
    COACH_SURFACE_ROLES,
    is_assistant_only,
    is_coach_supervisor,
    require_coach_lead_surface,
    require_coach_surface,
)


def test_role_literal_is_identical_in_both_hand_synced_copies() -> None:
    # claims.py re-declares the identity Role literal by hand (shared/ must
    # not import contexts/); a role added to one and not the other makes
    # membership rows fail to deserialize.
    assert set(get_args(auth_claims.Role)) == set(get_args(identity_models.Role))
    assert "assistant_coach" in get_args(auth_claims.Role)


def test_role_privilege_order_places_assistant_between_parent_and_coach() -> None:
    assert _ROLE_PRIVILEGE["student"] == _ROLE_PRIVILEGE["parent"]
    assert (
        _ROLE_PRIVILEGE["parent"]
        < _ROLE_PRIVILEGE["assistant_coach"]
        < _ROLE_PRIVILEGE["coach"]
        < _ROLE_PRIVILEGE["admin"]
        < _ROLE_PRIVILEGE["owner"]
    )
    # Coach -> assistant is a demotion (membership revoked first); the
    # reverse is a promotion (directory written first).
    assert _lowers_privilege(["coach"], "assistant_coach") is True
    assert _lowers_privilege(["assistant_coach"], "coach") is False
    assert _lowers_privilege(["parent"], "assistant_coach") is False


def _claims(*roles: str) -> AuthClaims:
    return AuthClaims(
        user_id="u",
        email="u@example.com",
        academy_id="acad",
        roles=tuple(roles),  # type: ignore[arg-type]
    )


def test_assistant_is_on_the_coach_surface_but_never_a_supervisor() -> None:
    assert "assistant_coach" in COACH_SURFACE_ROLES
    assert is_coach_supervisor(_claims("assistant_coach")) is False
    assert is_assistant_only(_claims("assistant_coach")) is True
    assert is_assistant_only(_claims("assistant_coach", "admin")) is False
    assert is_assistant_only(_claims("coach")) is False


def _app(claims: AuthClaims) -> TestClient:
    app = FastAPI()

    @app.get("/surface")
    async def _surface(c: AuthClaims = Depends(require_coach_surface())) -> dict[str, str]:
        return {"user": c.user_id}

    @app.get("/lead")
    async def _lead(c: AuthClaims = Depends(require_coach_lead_surface())) -> dict[str, str]:
        return {"user": c.user_id}

    app.dependency_overrides[get_auth_claims] = lambda: claims
    return TestClient(app)


@pytest.mark.parametrize(
    ("roles", "surface", "lead"),
    [
        (("coach",), 200, 200),
        (("admin",), 200, 200),
        (("owner",), 200, 200),
        (("assistant_coach",), 200, 404),
        (("assistant_coach", "coach"), 200, 200),
        (("parent",), 404, 404),
        (("student",), 404, 404),
        ((), 404, 404),
    ],
)
def test_guards_by_role(roles: tuple[str, ...], surface: int, lead: int) -> None:
    client = _app(_claims(*roles))
    assert client.get("/surface").status_code == surface
    assert client.get("/lead").status_code == lead
