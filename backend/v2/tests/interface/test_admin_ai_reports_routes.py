"""Interface tests for ``POST /admin/reports/month-close/narrative`` (B5)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.ai.application.use_cases.narrate_month_close import (
    FixFirst,
    MonthCloseNarrative,
)
from backend.v2.contexts.ai.domain.errors import AiDisabled, AiNotEntitled
from backend.v2.interfaces.admin.ai_reports_routes import get_ai_reports
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class FakeNarrate:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def execute(self, *, period: str, approver: str) -> MonthCloseNarrative:
        self.calls.append({"period": period, "approver": approver})
        if self.error is not None:
            raise self.error
        return MonthCloseNarrative(
            summary="Billed $1234 and collected $900.",
            fix_first=[FixFirst(text="Add a card", href="/admin/families/par-0")],
            prompt_version="month-close-narrator-v1",
            generated_at=datetime(2026, 9, 30, tzinfo=UTC),
        )


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _client(role: str, narrate: FakeNarrate | None) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    comp = None if narrate is None else SimpleNamespace(narrate_month_close=narrate)
    app.dependency_overrides[get_ai_reports] = lambda: comp
    return TestClient(app)


URL = "/api/v2/admin/reports/month-close/narrative"


def test_owner_gets_the_narrative_and_is_the_approver() -> None:
    narrate = FakeNarrate()
    resp = _client("owner", narrate).post(f"{URL}?period=2026-09")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == "Billed $1234 and collected $900."
    assert body["fix_first"] == [{"text": "Add a card", "href": "/admin/families/par-0"}]
    assert body["prompt_version"] == "month-close-narrator-v1"
    assert body["generated_at"].startswith("2026-09-30")
    assert narrate.calls == [{"period": "2026-09", "approver": "u-owner"}]


@pytest.mark.parametrize("role", ["admin", "coach", "parent"])
def test_non_owners_are_404(role: str) -> None:
    narrate = FakeNarrate()
    assert _client(role, narrate).post(f"{URL}?period=2026-09").status_code == 404
    assert narrate.calls == []


@pytest.mark.parametrize("query", ["", "?period=2026-13", "?period=Sept"])
def test_a_bad_or_missing_period_is_422(query: str) -> None:
    narrate = FakeNarrate()
    assert _client("owner", narrate).post(f"{URL}{query}").status_code == 422
    assert narrate.calls == []


def test_ai_off_is_a_503_with_the_disabled_code() -> None:
    resp = _client("owner", FakeNarrate(AiDisabled("off"))).post(f"{URL}?period=2026-09")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "Ai.Disabled"


def test_no_entitlement_is_a_403_with_the_not_entitled_code() -> None:
    resp = _client("owner", FakeNarrate(AiNotEntitled("growth"))).post(f"{URL}?period=2026-09")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "Ai.NotEntitled"


def test_unwired_composition_is_503() -> None:
    assert _client("owner", None).post(f"{URL}?period=2026-09").status_code == 503
