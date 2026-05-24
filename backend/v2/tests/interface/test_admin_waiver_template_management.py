"""Admin waiver template management BFF routes."""

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
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


@dataclass
class FakeTemplateRepo:
    rows: dict[str, AdminWaiverTemplateRecord] = field(default_factory=dict)
    next_id: int = 1

    def make_id(self) -> str:
        template_id = f"wt-{self.next_id}"
        self.next_id += 1
        return template_id

    async def list_templates(self) -> list[AdminWaiverTemplateRecord]:
        return sorted(self.rows.values(), key=lambda row: row.updated_at, reverse=True)

    async def create_draft(self, template: AdminWaiverTemplateRecord) -> AdminWaiverTemplateRecord:
        self.rows[template.waiver_template_id] = template
        return template

    async def get_template(self, waiver_template_id: str) -> AdminWaiverTemplateRecord | None:
        return self.rows.get(waiver_template_id)

    async def publish_draft(
        self,
        *,
        waiver_template_id: str,
        version: str,
        content_hash: str,
        published_at: datetime,
    ) -> AdminWaiverTemplateRecord:
        for row_id, row in list(self.rows.items()):
            if row.status == "active":
                self.rows[row_id] = row.model_copy(update={"status": "superseded"})
        current = self.rows[waiver_template_id]
        published = current.model_copy(
            update={
                "status": "active",
                "version": version,
                "content_hash": content_hash,
                "effective_from": published_at,
                "published_at": published_at,
                "updated_at": published_at,
            }
        )
        self.rows[waiver_template_id] = published
        return published

    async def assign_to_registration(
        self, *, waiver_template_id: str, assigned_at: datetime
    ) -> AdminWaiverTemplateRecord:
        for row_id, row in list(self.rows.items()):
            if row.assigned_to_registration:
                self.rows[row_id] = row.model_copy(
                    update={"assigned_to_registration": False, "assigned_at": None}
                )
        current = self.rows[waiver_template_id]
        assigned = current.model_copy(
            update={
                "assigned_to_registration": True,
                "assigned_at": assigned_at,
                "updated_at": assigned_at,
            }
        )
        self.rows[waiver_template_id] = assigned
        return assigned


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


@pytest.fixture
def admin_template_client() -> Iterator[TestClient]:
    repo = FakeTemplateRepo()
    manager = ManageAdminWaiverTemplates(repo, id_factory=repo.make_id, clock=_now)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims("admin")
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        manage_admin_waiver_templates=manager
    )
    with TestClient(app) as client:
        yield client


def _persona_client(role: str) -> TestClient:
    repo = FakeTemplateRepo()
    manager = ManageAdminWaiverTemplates(repo, id_factory=repo.make_id, clock=_now)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        manage_admin_waiver_templates=manager
    )
    return TestClient(app)


def test_admin_can_create_list_and_publish_waiver_template(admin_template_client):
    created = admin_template_client.post(
        "/api/v2/admin/waivers/templates",
        json={
            "title": "Summer waiver",
            "body": "Parent agrees to academy safety rules.",
        },
    )

    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["title"] == "Summer waiver"
    assert draft["status"] == "draft"
    assert draft["version"] is None
    assert draft["content_hash"] is None

    listed = admin_template_client.get("/api/v2/admin/waivers/templates")
    assert listed.status_code == 200, listed.text
    assert listed.json()["templates"] == [draft]

    published = admin_template_client.post(
        f"/api/v2/admin/waivers/templates/{draft['waiver_template_id']}/publish"
    )

    assert published.status_code == 200, published.text
    body = published.json()
    assert body["waiver_template_id"] == draft["waiver_template_id"]
    assert body["status"] == "active"
    assert body["version"] == "1"
    assert body["content_hash"]
    assert body["effective_at"] is not None

    assigned = admin_template_client.post(
        f"/api/v2/admin/waivers/templates/{draft['waiver_template_id']}/assign-registration"
    )

    assert assigned.status_code == 200, assigned.text
    assigned_body = assigned.json()
    assert assigned_body["assigned_to_registration"] is True
    assert assigned_body["assigned_at"] is not None


def test_admin_can_create_template_with_content_alias(admin_template_client):
    response = admin_template_client.post(
        "/api/v2/admin/waivers/templates",
        json={"title": "Alias waiver", "content": "Content supplied by API client."},
    )

    assert response.status_code == 201, response.text
    assert response.json()["body"] == "Content supplied by API client."


def test_waiver_template_management_wrong_persona_404():
    payload = {"title": "No access", "body": "Denied"}
    with _persona_client("coach") as coach_client:
        assert coach_client.post("/api/v2/admin/waivers/templates", json=payload).status_code == 404
        assert coach_client.post("/api/v2/admin/waivers/templates/wt-1/publish").status_code == 404
        assert (
            coach_client.post(
                "/api/v2/admin/waivers/templates/wt-1/assign-registration"
            ).status_code
            == 404
        )
    with _persona_client("parent") as parent_client:
        assert parent_client.get("/api/v2/admin/waivers/templates").status_code == 404
