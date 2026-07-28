from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.application.list_my_memberships_use_case import (
    ListMyMembershipsUseCase,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership
from backend.v2.interfaces.me_routes import router as me_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims


class _FakeMembershipsRepo:
    def __init__(self, memberships: list[AcademyMembership]) -> None:
        self._memberships = memberships

    async def list_memberships_for_user(self, user_id: str) -> list[AcademyMembership]:
        return [m for m in self._memberships if m.user_id == user_id]


class _FakeAcademyRepo:
    def __init__(self, names: dict[str, dict[str, str]]) -> None:
        self._names = names

    async def find_by_id(self, academy_id: str) -> dict[str, str] | None:
        return self._names.get(academy_id)


def _make_app(memberships: list[AcademyMembership], names: dict[str, dict[str, str]]) -> FastAPI:
    app = FastAPI()
    app.include_router(me_router, prefix="/api/v2")
    app.state.list_my_memberships = ListMyMembershipsUseCase(
        memberships=_FakeMembershipsRepo(memberships),
        academies=_FakeAcademyRepo(names),
    )

    async def _claims() -> AuthClaims:
        return AuthClaims(
            user_id="u-admin",
            email="admin@example.com",
            academy_id="academy-a",
            roles=("admin",),
        )

    app.dependency_overrides[get_auth_claims] = _claims
    return app


def test_single_membership_marks_active_academy_as_default() -> None:
    memberships = [
        AcademyMembership(
            membership_id="m1",
            academy_id="academy-a",
            user_id="u-admin",
            roles=("admin",),
            status="active",
        )
    ]
    names = {"academy-a": {"display_name": "Academy A", "slug": "academy-a"}}
    app = _make_app(memberships, names)

    with TestClient(app) as client:
        response = client.get("/api/v2/me/memberships")

    assert response.status_code == 200
    body = response.json()
    assert body["active_academy_id"] == "academy-a"
    assert body["memberships"] == [
        {
            "academy_id": "academy-a",
            "academy_name": "Academy A",
            "academy_slug": "academy-a",
            "roles": ["admin"],
            "status": "active",
            "is_default": True,
        }
    ]


def test_multiple_memberships_only_active_academy_is_default() -> None:
    memberships = [
        AcademyMembership(
            membership_id="m1",
            academy_id="academy-a",
            user_id="u-admin",
            roles=("admin",),
            status="active",
        ),
        AcademyMembership(
            membership_id="m2",
            academy_id="academy-b",
            user_id="u-admin",
            roles=("coach",),
            status="active",
        ),
        # Inactive/removed membership must be filtered out server-side.
        AcademyMembership(
            membership_id="m3",
            academy_id="academy-c",
            user_id="u-admin",
            roles=("admin",),
            status="removed",
        ),
    ]
    names = {
        "academy-a": {"display_name": "Academy A", "slug": "academy-a"},
        "academy-b": {"display_name": "Academy B", "slug": "academy-b"},
    }
    app = _make_app(memberships, names)

    with TestClient(app) as client:
        response = client.get("/api/v2/me/memberships")

    assert response.status_code == 200
    body = response.json()
    assert body["active_academy_id"] == "academy-a"
    assert [m["academy_id"] for m in body["memberships"]] == ["academy-a", "academy-b"]
    assert body["memberships"][0]["is_default"] is True
    assert body["memberships"][1]["is_default"] is False


def test_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(me_router, prefix="/api/v2")
    app.state.list_my_memberships = ListMyMembershipsUseCase(
        memberships=_FakeMembershipsRepo([]),
        academies=_FakeAcademyRepo({}),
    )

    with TestClient(app) as client:
        response = client.get("/api/v2/me/memberships")

    assert response.status_code == 401
