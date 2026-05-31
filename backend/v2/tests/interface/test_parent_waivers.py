"""Parent waiver read/sign BFF tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    ParentWaiverRequirement,
    ParentWaiverStudentStatus,
)
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent") -> AuthClaims:
    return AuthClaims(
        user_id=f"{role}-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


class _FakeExecutor:
    """Wraps a coroutine function as a use-case object with .execute()."""

    def __init__(self, fn):  # type: ignore[type-arg]
        self._fn = fn

    async def execute(self, **kwargs):  # type: ignore[override]
        return await self._fn(**kwargs)


@dataclass
class _ParentWaiverUseCases:
    signed_student_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.get_parent_waiver_requirement = _FakeExecutor(self._get_requirement)
        self.accept_parent_waiver = _FakeExecutor(self._accept)

    async def _get_requirement(self, *, parent_id: str) -> ParentWaiverRequirement:
        _ = parent_id
        return self._payload()

    async def _accept(
        self,
        *,
        parent_id: str,
        signer_name: str | None,
        signer_email: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ParentWaiverRequirement:
        _ = (parent_id, signer_name, signer_email, ip_address, user_agent)
        self.signed_student_ids.update({"st-1", "st-2"})
        return self._payload()

    def _payload(self) -> ParentWaiverRequirement:
        students = [
            ParentWaiverStudentStatus(
                student_id=sid,
                student_name=name,
                status="signed" if sid in self.signed_student_ids else "pending",
                signed_at=datetime(2026, 5, 28, 12, tzinfo=UTC)
                if sid in self.signed_student_ids
                else None,
                waiver_version="2026.1" if sid in self.signed_student_ids else None,
            )
            for sid, name in (("st-1", "Asha Rao"), ("st-2", "Dev Rao"))
        ]
        return ParentWaiverRequirement(
            required=True,
            waiver_template_id="wt-1",
            title="Annual waiver",
            version="2026.1",
            body="Waiver body",
            students=students,
        )


@contextmanager
def _make_client(role: str = "parent") -> Iterator[tuple[TestClient, _ParentWaiverUseCases]]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    use_cases = _ParentWaiverUseCases()
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        yield client, use_cases


def test_parent_gets_required_waiver_for_active_children() -> None:
    with _make_client() as (client, _use_cases):
        response = client.get("/api/v2/parent/waivers/current")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["required"] is True
    assert body["title"] == "Annual waiver"
    assert [row["status"] for row in body["students"]] == ["pending", "pending"]


def test_parent_accepts_required_waiver_for_all_active_children() -> None:
    with _make_client() as (client, use_cases):
        response = client.post("/api/v2/parent/waivers/accept", json={"signer_name": "Parent One"})

    assert response.status_code == 200, response.text
    assert use_cases.signed_student_ids == {"st-1", "st-2"}
    body = response.json()
    assert [row["status"] for row in body["students"]] == ["signed", "signed"]
