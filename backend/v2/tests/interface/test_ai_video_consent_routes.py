"""Parent and admin AI/video consent routes (Phase 3 E1).

The real use cases over a small in-memory store for one academy; tenant
isolation is proven on mongomock in ``application/test_ai_video_consent.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.onboarding.application.use_cases.ai_video_consent import (
    AiVideoConsentChild,
    ListAdminAiVideoConsents,
    ParentAiVideoConsent,
)
from backend.v2.contexts.onboarding.domain.ai_video_consent import AiVideoConsent
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

PLACEHOLDER = "ai_video_consent_v0_placeholder"


class _Store:
    """One academy's consents; mirrors the Mongo repo's grant/revoke semantics."""

    def __init__(self) -> None:
        self.children = {
            "p-rao": [AiVideoConsentChild(student_id="s-asha", student_name="Asha Rao")],
            "p-other": [AiVideoConsentChild(student_id="s-other", student_name="Other Kid")],
        }
        self.rows: dict[str, AiVideoConsent] = {}

    async def children_of(self, parent_id: str) -> list[AiVideoConsentChild]:
        return self.children.get(parent_id, [])

    async def consents_for(self, student_ids: list[str]) -> dict[str, AiVideoConsent]:
        return {sid: self.rows[sid] for sid in student_ids if sid in self.rows}

    async def save_grant(self, consent: AiVideoConsent) -> None:
        self.rows[consent.student_id] = consent

    async def save_revoke(self, student_id: str, *, revoked_at: datetime, revoked_by: str) -> None:
        row = self.rows.get(student_id)
        if row is not None and row.status == "granted":
            self.rows[student_id] = row.model_copy(
                update={"status": "revoked", "revoked_at": revoked_at, "revoked_by": revoked_by}
            )

    async def list_all(self) -> list[tuple[AiVideoConsent, str]]:
        names = {c.student_id: c.student_name for kids in self.children.values() for c in kids}
        return [(row, names[sid]) for sid, row in self.rows.items()]

    async def get_for_academy(self, academy_id: str, student_id: str) -> AiVideoConsent | None:
        return self.rows.get(student_id)


@contextmanager
def _client(role: str = "parent", user_id: str = "p-rao") -> Iterator[tuple[TestClient, _Store]]:
    store = _Store()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.include_router(admin_router, prefix="/api/v2")
    claims = AuthClaims(
        user_id=user_id,
        email=f"{user_id}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_parent_use_cases] = lambda: SimpleNamespace(
        ai_video_consent=ParentAiVideoConsent(consents=store)
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        list_ai_video_consents=ListAdminAiVideoConsents(consents=store)
    )
    with TestClient(app) as client:
        yield client, store


def _grant(client: TestClient, student_id: str = "s-asha", **body: object):
    return client.post(
        f"/api/v2/parent/waivers/ai-video-consent/{student_id}/grant",
        json={"text_version": PLACEHOLDER, "consent": True, **body},
    )


def test_parent_reads_placeholder_text_and_no_consent_by_default() -> None:
    with _client() as (client, _store):
        response = client.get("/api/v2/parent/waivers/ai-video-consent")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["placeholder"] is True
    assert body["text_version"] == PLACEHOLDER
    assert "[vendor to be confirmed]" in body["text"]
    assert "[30, 60 or 90] days" in body["text"]
    assert [(c["student_id"], c["status"]) for c in body["children"]] == [("s-asha", "none")]


def test_parent_grants_then_revokes() -> None:
    with _client() as (client, store):
        granted = _grant(client)
        assert granted.status_code == 200, granted.text
        assert granted.json()["children"][0]["status"] == "granted"
        assert store.rows["s-asha"].accepted_by == "p-rao"
        assert store.rows["s-asha"].accepted_by_email == "p-rao@example.com"

        revoked = client.post("/api/v2/parent/waivers/ai-video-consent/s-asha/revoke")
        assert revoked.status_code == 200, revoked.text
        child = revoked.json()["children"][0]
        assert child["status"] == "revoked" and child["revoked_at"]


def test_grant_needs_the_ticked_box_and_the_current_text() -> None:
    with _client() as (client, store):
        assert _grant(client, consent=False).status_code == 422
        stale = _grant(client, text_version="ai_video_consent_v-old")
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "Onboarding.AiVideoConsentTextChanged"
        assert _grant(client, unexpected=True).status_code == 422
    assert store.rows == {}


def test_another_familys_child_is_404() -> None:
    with _client() as (client, store):
        assert _grant(client, "s-other").status_code == 404
        assert (
            client.post("/api/v2/parent/waivers/ai-video-consent/s-other/revoke").status_code == 404
        )
    assert store.rows == {}


@pytest.mark.parametrize("role", ["coach", "admin", "student"])
def test_parent_routes_are_404_for_other_personas(role: str) -> None:
    with _client(role=role) as (client, store):
        assert client.get("/api/v2/parent/waivers/ai-video-consent").status_code == 404
        assert _grant(client).status_code == 404
        assert (
            client.post("/api/v2/parent/waivers/ai-video-consent/s-asha/revoke").status_code == 404
        )
    assert store.rows == {}


def test_admin_sees_per_child_status_read_only() -> None:
    with _client() as (client, _store):
        _grant(client)
    with _client(role="admin", user_id="admin-1") as (client, store):
        store.rows["s-asha"] = AiVideoConsent(
            student_id="s-asha",
            status="granted",
            text_version=PLACEHOLDER,
            accepted_at=datetime(2026, 11, 5),
            accepted_by="p-rao",
        )
        response = client.get("/api/v2/admin/waivers/ai-video-consents")
        assert response.status_code == 200, response.text
        assert [(c["student_name"], c["status"]) for c in response.json()["children"]] == [
            ("Asha Rao", "granted")
        ]
        # Read-only: the admin cannot grant or revoke for a family.
        assert _grant(client).status_code == 404


@pytest.mark.parametrize("role", ["parent", "coach"])
def test_admin_route_is_404_for_other_personas(role: str) -> None:
    with _client(role=role) as (client, _store):
        assert client.get("/api/v2/admin/waivers/ai-video-consents").status_code == 404
