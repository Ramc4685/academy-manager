"""Interface tests for ``GET /admin/payments/collections``.

The route is a thin pass-through: persona gate, query validation, and a
``response_model`` that shapes whatever the read model returned. The read
model itself is covered by the mongomock contract tests; here it is a fake
that records its arguments.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.admin.collections_routes import get_admin_collections
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

_FAMILY: dict[str, Any] = {
    "parent_id": "p-1",
    "parent_name": "Parent One",
    "parent_email": "p1@example.com",
    "students": [{"student_id": "s-1", "name": "Kid", "session_title": "Monday Juniors"}],
    "invoices": [
        {
            "invoice_id": "inv-1",
            "invoice_number": "INV-1",
            "period": "2026-09",
            "status": "open",
            "total_cents": 10_000,
            "balance_due_cents": 10_000,
            "due_date": "2026-09-05",
            "delivery_status": "sent",
        }
    ],
    "balance_cents": 10_000,
    "leftover_balance_cents": 0,
    "autopay": {
        "status": "eligible",
        "card_last4": "4242",
        "charge_on": "2026-09-05",
        "notice_sent_at": None,
    },
    "failure": {
        "reason": "Your card was declined.",
        "attempt_count": 1,
        "max_attempts": 4,
        "next_retry_on": "2026-09-12",
        "disabled": False,
    },
    "pause": None,
    "paid": None,
    "last_reminder_at": None,
    "actions": ["message", "record_payment"],
}


def _view(period: str) -> dict[str, Any]:
    keys = ["failed_autopay", "past_due", "awaiting", "autopay_scheduled", "paused", "paid"]
    buckets = [{"key": key, "count": 0, "total_cents": 0, "families": []} for key in keys]
    buckets[0] = {"key": "failed_autopay", "count": 1, "total_cents": 10_000, "families": [_FAMILY]}
    return {
        "period": period,
        "generated_at": "2026-09-10T15:00:00+00:00",
        "timezone": "America/Chicago",
        "totals": {
            "owed_cents": 10_000,
            "autopay_scheduled_cents": 0,
            "autopay_scheduled_count": 0,
            "needs_action_count": 1,
            "collected_cents": 0,
        },
        "buckets": buckets,
        # Extra key the view must tolerate (``extra="ignore"``).
        "internal_debug_marker": True,
    }


class FakeCollectionsReader:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def build(self, period: str | None = None, *, debug: bool = False) -> dict[str, Any]:
        self.calls.append({"period": period, "debug": debug})
        view = _view(period or "2026-09")
        if debug:
            view["unclassified"] = [{"parent_id": None, "error": "orphan inv-x"}]
        return view


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _make_app(role: str, reader: FakeCollectionsReader) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_collections] = lambda: reader
    return app


@pytest.fixture
def reader() -> FakeCollectionsReader:
    return FakeCollectionsReader()


@pytest.fixture
def admin(reader: FakeCollectionsReader) -> Iterator[TestClient]:
    with TestClient(_make_app("admin", reader)) as client:
        yield client


@pytest.fixture
def coach(reader: FakeCollectionsReader) -> Iterator[TestClient]:
    with TestClient(_make_app("coach", reader)) as client:
        yield client


def test_admin_gets_the_bucket_view(admin: TestClient, reader: FakeCollectionsReader) -> None:
    resp = admin.get("/api/v2/admin/payments/collections?period=2026-09")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "2026-09"
    assert body["timezone"] == "America/Chicago"
    assert body["totals"]["needs_action_count"] == 1
    assert [b["key"] for b in body["buckets"]] == [
        "failed_autopay",
        "past_due",
        "awaiting",
        "autopay_scheduled",
        "paused",
        "paid",
    ]
    assert body["buckets"][0]["key"] == "failed_autopay"
    family = body["buckets"][0]["families"][0]
    assert family["parent_id"] == "p-1"
    assert family["actions"] == ["message", "record_payment"]
    assert family["failure"]["max_attempts"] == 4
    assert family["invoices"][0]["invoice_id"] == "inv-1"
    assert "internal_debug_marker" not in body
    assert body["unclassified"] is None
    assert reader.calls == [{"period": "2026-09", "debug": False}]


def test_coach_is_404(coach: TestClient, reader: FakeCollectionsReader) -> None:
    resp = coach.get("/api/v2/admin/payments/collections")

    assert resp.status_code == 404
    assert reader.calls == []


def test_bad_period_is_422(admin: TestClient, reader: FakeCollectionsReader) -> None:
    resp = admin.get("/api/v2/admin/payments/collections?period=2026-13")

    assert resp.status_code == 422
    assert reader.calls == []


def test_no_period_passes_none_to_the_reader(
    admin: TestClient, reader: FakeCollectionsReader
) -> None:
    resp = admin.get("/api/v2/admin/payments/collections")

    assert resp.status_code == 200, resp.text
    assert reader.calls == [{"period": None, "debug": False}]


def test_debug_flag_reaches_the_reader_and_unclassified_is_returned(
    admin: TestClient, reader: FakeCollectionsReader
) -> None:
    resp = admin.get("/api/v2/admin/payments/collections?period=2026-09&debug=1")

    assert resp.status_code == 200, resp.text
    assert reader.calls == [{"period": "2026-09", "debug": True}]
    assert resp.json()["unclassified"] == [{"parent_id": None, "error": "orphan inv-x"}]
