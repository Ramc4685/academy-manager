"""``GET /parent/onboarding/waiver``: the waivers to sign for the chosen class."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.onboarding.domain.models import Waiver
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

NOW = datetime(2026, 9, 29, tzinfo=UTC)


def _waiver(waiver_id: str, title: str) -> Waiver:
    return Waiver(
        waiver_id=waiver_id,
        academy_id="acad",
        version="1",
        text=f"{title} text",
        content_hash="h",
        effective_from=NOW,
        title=title,
    )


def _client(use_cases: SimpleNamespace) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="parent-1", email="p@example.com", academy_id="acad", roles=("parent",)
    )
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    return TestClient(app)


def test_single_waiver_reads_as_before_with_a_one_item_list() -> None:
    async def waivers(session_id):
        return [_waiver("wt-1", "Liability")], False

    response = _client(SimpleNamespace(get_registration_waivers=waivers)).get(
        "/api/v2/parent/onboarding/waiver"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["version"] == "1"
    assert body["body"] == "Liability text"
    assert body["class_first"] is False
    assert [w["waiver_template_id"] for w in body["waivers"]] == ["wt-1"]


def test_the_chosen_class_is_passed_through_and_program_waivers_are_listed() -> None:
    seen: list[str | None] = []

    async def waivers(session_id):
        seen.append(session_id)
        return [_waiver("wt-1", "Liability"), _waiver("wt-2", "Photo consent")], True

    response = _client(SimpleNamespace(get_registration_waivers=waivers)).get(
        "/api/v2/parent/onboarding/waiver?session_id=s-juniors"
    )

    assert seen == ["s-juniors"]
    body = response.json()
    assert body["class_first"] is True
    assert [w["title"] for w in body["waivers"]] == ["Liability", "Photo consent"]
    # The flat fields stay the first waiver's.
    assert body["body"] == "Liability text"


def test_no_waiver_configured() -> None:
    async def waivers(session_id):
        return [], False

    response = _client(SimpleNamespace(get_registration_waivers=waivers)).get(
        "/api/v2/parent/onboarding/waiver"
    )

    assert response.json()["configured"] is False
    assert response.json()["waivers"] == []
