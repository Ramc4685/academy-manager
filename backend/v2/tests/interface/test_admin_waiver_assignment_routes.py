"""Waiver assignment and per-student status BFF routes (Settings Phase 6)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
    ManageAdminWaiverTemplates,
    ProgramRef,
)
from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    ParentWaiverSignature,
)
from backend.v2.contexts.onboarding.application.use_cases.student_waiver_status import (
    GetStudentWaiverStatus,
)
from backend.v2.contexts.onboarding.domain.waiver_assignment import WaiverAssignment
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

NOW = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)


@dataclass
class FakeRepo:
    rows: dict[str, AdminWaiverTemplateRecord] = field(default_factory=dict)

    async def list_templates(self) -> list[AdminWaiverTemplateRecord]:
        return list(self.rows.values())

    async def create_draft(self, template: AdminWaiverTemplateRecord) -> AdminWaiverTemplateRecord:
        self.rows[template.waiver_template_id] = template
        return template

    async def get_template(self, waiver_template_id: str) -> AdminWaiverTemplateRecord | None:
        return self.rows.get(waiver_template_id)

    async def publish_draft(self, **_kwargs: object) -> AdminWaiverTemplateRecord:
        raise NotImplementedError

    async def assign_to_registration(self, **_kwargs: object) -> AdminWaiverTemplateRecord:
        raise NotImplementedError

    async def set_assignment(
        self, *, waiver_template_id: str, assignment: WaiverAssignment, assigned_at: datetime
    ) -> AdminWaiverTemplateRecord:
        updated = self.rows[waiver_template_id].model_copy(
            update={
                "required": assignment.required,
                "scope": assignment.scope,
                "program_ids": list(assignment.program_ids),
                "assigned_to_registration": assignment.for_all_families,
                "assigned_at": assigned_at if assignment.for_all_families else None,
            }
        )
        self.rows[waiver_template_id] = updated
        return updated


class Programs:
    async def list_programs(self) -> list[ProgramRef]:
        return [ProgramRef(program_id="prog-juniors", name="Juniors")]


class FakeStatusReader:
    async def list_required_templates(self) -> list[AdminWaiverTemplateRecord]:
        return [
            AdminWaiverTemplateRecord(
                waiver_template_id="wt-1",
                title="Liability waiver",
                body="b",
                status="active",
                version="2",
                content_hash="h2",
                required=True,
                updated_at=NOW,
                lineage_key="wl-1",
            )
        ]

    async def program_ids_for_students(self, student_ids: list[str]) -> dict[str, set[str]]:
        return {}

    async def signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[tuple[str, str], ParentWaiverSignature]:
        return {
            ("st-1", "wl-1"): ParentWaiverSignature(
                student_id="st-1",
                waiver_template_id="wt-0",
                content_hash="h1",
                signed_at=NOW,
                lineage_key="wl-1",
                waiver_signature_id="ws-9",
                signed_version="1",
            )
        }


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _client(role: str = "admin") -> tuple[TestClient, FakeRepo]:
    repo = FakeRepo(
        rows={
            "wt-live": AdminWaiverTemplateRecord(
                waiver_template_id="wt-live",
                title="Photo consent",
                body="b",
                status="active",
                version="1",
                content_hash="h",
                updated_at=NOW,
                lineage_key="wl-photo",
            ),
            "wt-draft": AdminWaiverTemplateRecord(
                waiver_template_id="wt-draft",
                title="Draft",
                body="b",
                status="draft",
                updated_at=NOW,
            ),
        }
    )
    manager = ManageAdminWaiverTemplates(repo, programs=Programs(), clock=lambda: NOW)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.state.admin_student_waivers = SimpleNamespace(
        get_student_waiver_status=GetStudentWaiverStatus(FakeStatusReader())
    )
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        manage_admin_waiver_templates=manager
    )
    return TestClient(app), repo


@pytest.fixture
def admin_client() -> Iterator[TestClient]:
    client, _repo = _client()
    with client:
        yield client


def test_list_returns_assignment_fields_and_the_academys_programs(admin_client) -> None:
    response = admin_client.get("/api/v2/admin/waivers/templates")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["programs"] == [{"program_id": "prog-juniors", "name": "Juniors"}]
    live = next(t for t in body["templates"] if t["waiver_template_id"] == "wt-live")
    assert live["lineage_key"] == "wl-photo"
    assert live["required"] is False
    assert live["scope"] == "all"
    assert live["program_ids"] == []


def test_assign_to_a_program_then_to_all_families(admin_client) -> None:
    programs = admin_client.put(
        "/api/v2/admin/waivers/templates/wt-live/assignment",
        json={"required": True, "scope": "programs", "program_ids": ["prog-juniors"]},
    )

    assert programs.status_code == 200, programs.text
    assert programs.json()["required"] is True
    assert programs.json()["scope"] == "programs"
    assert programs.json()["program_ids"] == ["prog-juniors"]
    assert programs.json()["assigned_to_registration"] is False

    everyone = admin_client.put(
        "/api/v2/admin/waivers/templates/wt-live/assignment",
        json={"required": True, "scope": "all"},
    )

    assert everyone.status_code == 200, everyone.text
    assert everyone.json()["program_ids"] == []
    assert everyone.json()["assigned_to_registration"] is True


@pytest.mark.parametrize(
    ("waiver_id", "payload", "status"),
    [
        ("wt-live", {"required": True, "scope": "programs", "program_ids": []}, 409),
        ("wt-live", {"required": True, "scope": "programs", "program_ids": ["nope"]}, 409),
        ("wt-draft", {"required": True, "scope": "all"}, 409),
        ("wt-missing", {"required": True, "scope": "all"}, 404),
    ],
)
def test_assign_rejects_bad_requests(admin_client, waiver_id, payload, status) -> None:
    response = admin_client.put(
        f"/api/v2/admin/waivers/templates/{waiver_id}/assignment", json=payload
    )

    assert response.status_code == status, response.text


def test_assign_is_admin_only() -> None:
    for role in ("coach", "parent"):
        client, _repo = _client(role)
        with client:
            response = client.put(
                "/api/v2/admin/waivers/templates/wt-live/assignment",
                json={"required": True, "scope": "all"},
            )
            assert response.status_code == 404


def test_create_a_new_version_draft_keeps_the_waivers_lineage(admin_client) -> None:
    response = admin_client.post(
        "/api/v2/admin/waivers/templates",
        json={"title": "Photo consent", "body": "v2", "based_on_waiver_template_id": "wt-live"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["lineage_key"] == "wl-photo"
    missing = admin_client.post(
        "/api/v2/admin/waivers/templates",
        json={"title": "x", "body": "y", "based_on_waiver_template_id": "nope"},
    )
    assert missing.status_code == 404


def test_student_waiver_status_shows_older_version_with_a_signature_link(admin_client) -> None:
    response = admin_client.get("/api/v2/admin/waivers/students/st-1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["student_id"] == "st-1"
    assert body["waivers"] == [
        {
            "waiver_template_id": "wt-1",
            "lineage_key": "wl-1",
            "title": "Liability waiver",
            "version": "2",
            "status": "older_version",
            "signed_version": "1",
            "signed_at": "2026-09-29T09:00:00Z",
            "signature_id": "ws-9",
        }
    ]
