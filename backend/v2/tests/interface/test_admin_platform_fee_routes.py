"""Interface tests for ``GET /admin/billing/platform-fee`` (Phase 2 A1).

Read-only, any academy admin (no owner gate); other personas 404; 503 when
the reader is not wired.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.application_fee import (
    APPLICATION_FEE_AGREEMENT_TEXT,
    APPLICATION_FEE_AGREEMENT_VERSION,
    ApplicationFeeResult,
)
from backend.v2.interfaces.admin.platform_fee_routes import get_admin_platform_fee
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

URL = "/api/v2/admin/billing/platform-fee"
AT = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)


class _Reader:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self) -> ApplicationFeeResult:
        self.calls += 1
        return ApplicationFeeResult(
            academy_id="acad",
            application_fee_bps=100,
            agreement_version=APPLICATION_FEE_AGREEMENT_VERSION,
            accepted_at=AT,
            accepted_by="Jane Owner",
        )


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _client(role: str, reader: _Reader | None) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_platform_fee] = lambda: reader
    return TestClient(app)


def test_an_admin_reads_the_rate_and_agreement() -> None:
    reader = _Reader()
    with _client("admin", reader) as client:
        resp = client.get(URL)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "application_fee_bps": 100,
        "agreement_version": APPLICATION_FEE_AGREEMENT_VERSION,
        "agreement_text": APPLICATION_FEE_AGREEMENT_TEXT,
        "accepted_at": AT.isoformat().replace("+00:00", "Z"),
        "accepted_by": "Jane Owner",
    }
    assert reader.calls == 1


@pytest.mark.parametrize("role", ["coach", "parent"])
def test_other_personas_are_404(role: str) -> None:
    reader = _Reader()
    with _client(role, reader) as client:
        assert client.get(URL).status_code == 404
    assert reader.calls == 0


def test_unwired_reader_is_503() -> None:
    with _client("admin", None) as client:
        assert client.get(URL).status_code == 503
