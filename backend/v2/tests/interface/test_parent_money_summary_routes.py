"""S57: GET /parent/money-summary, invoice and payment labels."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class _Money:
    def __init__(self) -> None:
        self.summary_calls: list[str] = []

    async def summary(self, parent_id: str) -> dict:
        self.summary_calls.append(parent_id)
        return {
            "currency": "usd", "amount_due_cents": 6000, "due_date": date(2026, 12, 1),
            "overdue": False, "days_overdue": 0, "multiple_due_dates": False,
            "can_pay_online": True,
            "lines": [{"kind": "child", "student_id": "sam", "label": "Sam Demo",
                       "detail": None, "amount_cents": 6000}],
            "periods": [], "last_payment": None,
        }

    async def payment_extras(self, parent_id: str, rows) -> dict:
        return {"pay-1": {"student_names": ["Sam Demo"], "method_label": "Paid in cash"}}


class _UseCases:
    def __init__(self, money) -> None:
        self.parent_money = money

    async def list_payments_for_parent(self, parent_id: str):
        return [SimpleNamespace(
            payment_id="pay-1", amount_cents=6000, currency="usd", status="succeeded",
            refunded_cents=0, created_at=datetime(2026, 10, 3, tzinfo=UTC), session_id=None,
            stripe_invoice_id=None, stripe_payment_intent_id=None, invoice_id="i1",
            invoice_period="2026-10",
        )]


@contextmanager
def _client(use_cases, role: str = "parent") -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="parent-1", email="p@example.com", academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        yield client


def test_money_summary_is_the_callers_own() -> None:
    money = _Money()
    with _client(_UseCases(money)) as client:
        res = client.get("/api/v2/parent/money-summary")
    assert res.status_code == 200
    body = res.json()
    assert body["amount_due_cents"] == 6000
    assert body["due_date"] == "2026-12-01"
    assert body["lines"][0]["label"] == "Sam Demo"
    assert money.summary_calls == ["parent-1"]


def test_money_summary_refuses_a_coach() -> None:
    money = _Money()
    with _client(_UseCases(money), role="coach") as client:
        res = client.get("/api/v2/parent/money-summary")
    assert res.status_code in (401, 403, 404)
    assert money.summary_calls == []


def test_payment_history_names_the_child_and_method() -> None:
    with _client(_UseCases(_Money())) as client:
        res = client.get("/api/v2/parent/payments")
    row = res.json()["payments"][0]
    assert row["student_names"] == ["Sam Demo"]
    assert row["method_label"] == "Paid in cash"
