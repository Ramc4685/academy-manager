from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent") -> AuthClaims:
    return AuthClaims(
        user_id="parent-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


class _ParentUseCases:
    async def list_credits_for_parent(self, parent_id: str):
        return [
            CreditLedgerEntry(
                credit_id="credit-1",
                academy_id="acad",
                parent_id=parent_id,
                student_id="student-1",
                enrollment_id="enroll-1",
                type="EARLY_WITHDRAWAL_CREDIT",
                status="APPROVED",
                amount_cents=3750,
                remaining_amount_cents=2500,
                currency="usd",
                reason="Early withdrawal",
                expires_at=datetime(2027, 5, 20, tzinfo=timezone.utc),
                created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
            )
        ]


@contextmanager
def _make_client(role: str = "parent") -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_parent_use_cases] = lambda: _ParentUseCases()
    with TestClient(app) as client:
        yield client


def test_parent_credit_balance() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/credits")

    assert response.status_code == 200
    body = response.json()
    assert body["balance_cents"] == 2500
    assert body["credits"][0]["reason"] == "Early withdrawal"
    assert body["credits"][0]["remaining_amount_cents"] == 2500


def test_wrong_persona_cannot_read_parent_credits() -> None:
    with _make_client("admin") as client:
        response = client.get("/api/v2/parent/credits")

    assert response.status_code == 404
