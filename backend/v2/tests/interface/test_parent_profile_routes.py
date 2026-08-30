"""Interface tests for GET/PATCH /api/v2/parent/profile and /children/{id}.

Composition-level behaviour (ownership, audit, gap computation against a real
Mongo-shaped document) is covered in test_parent_composition.py. These tests
exercise route wiring only: response mapping, the 404-on-not-owned contract,
and the extra="forbid" field allow-list.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

_OWNED_STUDENT_ID = "stu-1"


def _profile_payload(*, phone: str | None = "+1 555 0100") -> dict[str, Any]:
    return {
        "user_id": "parent-1",
        "display_name": "Meera Raghavan",
        "email": "parent@example.com",
        "email_confirmed": False,
        "phone": phone,
        "children": [
            {
                "student_id": _OWNED_STUDENT_ID,
                "full_name": "Aanya Raghavan",
                "date_of_birth": "2015-04-02",
                "emergency_contact_name": None,
                "emergency_contact_phone": None,
                "medical_notes": None,
                "no_medical_conditions": False,
            }
        ],
        "gaps": {
            "parent": [] if phone else ["phone"],
            "children": {_OWNED_STUDENT_ID: ["emergency_contact_name", "emergency_contact_phone"]},
            "is_complete": False,
        },
    }


class _FakeUseCases:
    """Records calls and returns a canned profile — or None to simulate a
    student that isn't found or isn't this parent's, which the route must
    map to 404 without distinguishing the two cases."""

    def __init__(self) -> None:
        self.update_child_calls: list[tuple[str, str, Any]] = []

    async def get_parent_profile(self, parent_id: str) -> dict[str, Any] | None:
        return _profile_payload()

    async def update_parent_profile(self, parent_id: str, request: Any) -> dict[str, Any] | None:
        return _profile_payload(phone=request.phone)

    async def confirm_parent_email(self, parent_id: str) -> dict[str, Any] | None:
        payload = _profile_payload()
        payload["email_confirmed"] = True
        return payload

    async def update_parent_child(
        self, parent_id: str, student_id: str, request: Any
    ) -> dict[str, Any] | None:
        self.update_child_calls.append((parent_id, student_id, request))
        if student_id != _OWNED_STUDENT_ID:
            return None
        return _profile_payload()


def _parent_claims(user_id: str = "parent-1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{user_id}@example.com",
        academy_id="acad",
        roles=("parent",),
    )


def _build_app(claims: AuthClaims, use_cases: Any) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    return app


@pytest.fixture()
def use_cases() -> _FakeUseCases:
    return _FakeUseCases()


@pytest.fixture()
def client(use_cases: _FakeUseCases) -> Iterator[TestClient]:
    app = _build_app(_parent_claims(), use_cases)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_get_profile_returns_gaps(client: TestClient) -> None:
    response = client.get("/api/v2/parent/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Meera Raghavan"
    assert body["gaps"]["is_complete"] is False


def test_patch_profile_updates_phone(client: TestClient) -> None:
    response = client.patch("/api/v2/parent/profile", json={"phone": "+1 555 0199"})

    assert response.status_code == 200
    assert response.json()["phone"] == "+1 555 0199"


def test_patch_profile_rejects_unknown_fields(client: TestClient) -> None:
    """extra="forbid" is the field allow-list — a parent must never be able
    to smuggle status/parent_id/role fields through this endpoint."""
    response = client.patch(
        "/api/v2/parent/profile", json={"phone": "+1 555 0199", "status": "inactive"}
    )

    assert response.status_code == 422


def test_confirm_email_marks_confirmed(client: TestClient) -> None:
    response = client.post("/api/v2/parent/profile/confirm-email")

    assert response.status_code == 200
    assert response.json()["email_confirmed"] is True


def test_patch_child_updates_emergency_contact(client: TestClient) -> None:
    response = client.patch(
        f"/api/v2/parent/children/{_OWNED_STUDENT_ID}",
        json={
            "emergency_contact_name": "Vikram Raghavan",
            "emergency_contact_phone": "+1 555 0111",
        },
    )

    assert response.status_code == 200


def test_patch_child_not_owned_returns_404(client: TestClient, use_cases: _FakeUseCases) -> None:
    response = client.patch(
        "/api/v2/parent/children/someone-elses-child",
        json={"emergency_contact_name": "Should not land"},
    )

    assert response.status_code == 404
    # The use case was still called — the 404 comes from its None return,
    # confirming the route doesn't special-case student_id shapes itself.
    assert use_cases.update_child_calls[0][1] == "someone-elses-child"


def test_patch_child_rejects_disallowed_fields(client: TestClient) -> None:
    """status/parent_id/level must never be settable by a parent, no matter
    what the request body contains."""
    response = client.patch(
        f"/api/v2/parent/children/{_OWNED_STUDENT_ID}",
        json={"status": "withdrawn"},
    )

    assert response.status_code == 422


def test_patch_child_rejects_future_date_of_birth(client: TestClient) -> None:
    response = client.patch(
        f"/api/v2/parent/children/{_OWNED_STUDENT_ID}",
        json={"date_of_birth": "2099-01-01"},
    )

    assert response.status_code == 422
