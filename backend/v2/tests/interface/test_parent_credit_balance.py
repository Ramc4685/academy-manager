from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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


def _credit(
    *,
    credit_id: str,
    remaining: int,
    expires_at: datetime | None,
    status: str = "APPROVED",
) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        credit_id=credit_id,
        academy_id="acad",
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id=f"enroll-{credit_id}",
        type="EARLY_WITHDRAWAL_CREDIT",
        status=status,  # type: ignore[arg-type]
        amount_cents=3750,
        remaining_amount_cents=remaining,
        currency="usd",
        reason="Early withdrawal",
        expires_at=expires_at,
        created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )


class _ParentUseCases:
    def __init__(self, credits: list[CreditLedgerEntry] | None = None) -> None:
        self._credits = credits

    async def list_credits_for_parent(self, parent_id: str):
        if self._credits is not None:
            return self._credits
        return [_credit(credit_id="credit-1", remaining=2500, expires_at=datetime(2027, 5, 20, tzinfo=timezone.utc))]


@contextmanager
def _make_client(
    role: str = "parent",
    use_cases: _ParentUseCases | None = None,
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_parent_use_cases] = lambda: (use_cases or _ParentUseCases())
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


def test_balance_excludes_expired_credits() -> None:
    now = datetime.now(timezone.utc)
    use_cases = _ParentUseCases(
        credits=[
            _credit(credit_id="active", remaining=2500, expires_at=now + timedelta(days=10)),
            _credit(credit_id="expired", remaining=4000, expires_at=now - timedelta(days=1)),
            _credit(credit_id="never-expires", remaining=1000, expires_at=None),
        ]
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/credits")

    assert response.status_code == 200
    body = response.json()
    # Balance must match apply_available_credits semantics: only non-expired,
    # APPROVED, remaining_amount_cents > 0 credits count.
    assert body["balance_cents"] == 2500 + 1000
    # The expired credit is still shown in the list (so parent can see history),
    # but it does not inflate balance_cents.
    credit_ids = {c["credit_id"] for c in body["credits"]}
    assert credit_ids == {"active", "expired", "never-expires"}
