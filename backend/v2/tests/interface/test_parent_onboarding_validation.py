from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.onboarding.domain.models import Application, ChildProfile, ParentProfile
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims() -> AuthClaims:
    return AuthClaims(
        user_id="parent-1",
        email="parent@example.com",
        academy_id="acad",
        roles=("parent",),
    )


@dataclass
class _PatchApplication:
    received_child_profile: dict[str, object] | None = None

    async def execute(self, command) -> Application:
        self.received_child_profile = command.child_profile
        now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
        return Application(
            application_id=command.application_id,
            academy_id="acad",
            parent_user_id=command.caller_user_id,
            parent_email="parent@example.com",
            parent_profile=ParentProfile(),
            child_profile=ChildProfile(**(command.child_profile or {})),
            expires_at=now,
            created_at=now,
            updated_at=now,
        )


class _ParentUseCases:
    def __init__(self) -> None:
        self.patch_application = _PatchApplication()


@contextmanager
def _client() -> Iterator[tuple[TestClient, _ParentUseCases]]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    use_cases = _ParentUseCases()
    app.dependency_overrides[get_auth_claims] = _claims
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        yield client, use_cases


def test_parent_onboarding_rejects_invalid_child_date_of_birth() -> None:
    with _client() as (client, use_cases):
        response = client.patch(
            "/api/v2/parent/onboarding/app-1",
            json={"child_profile": {"first_name": "Ava", "date_of_birth": "2018-02-31"}},
        )

    assert response.status_code == 422
    assert use_cases.patch_application.received_child_profile is None


def test_parent_onboarding_accepts_iso_child_date_of_birth() -> None:
    with _client() as (client, use_cases):
        response = client.patch(
            "/api/v2/parent/onboarding/app-1",
            json={"child_profile": {"first_name": "Ava", "date_of_birth": "2018-02-28"}},
        )

    assert response.status_code == 200
    assert use_cases.patch_application.received_child_profile == {
        "first_name": "Ava",
        "last_name": "",
        "date_of_birth": "2018-02-28",
        "skill_level": "",
        "emergency_contact_name": "",
        "emergency_contact_phone": "",
        "medical_notes": "",
    }
