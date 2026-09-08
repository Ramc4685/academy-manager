"""Interface tests for ``GET /admin/reports/month-close``.

The route is a thin pass-through: owner gate, period validation, and a
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

from backend.v2.interfaces.admin.month_close_routes import get_admin_month_close
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _view(period: str) -> dict[str, Any]:
    return {
        "generated_at": "2026-09-20T15:00:00+00:00",
        "timezone": "America/Chicago",
        "period": period,
        "invoices": {
            "generated": 12,
            "emailed": 4,
            "autopay_notices": 7,
            "not_sent": 1,
            "voided": 1,
            "voided_cents": 5_000,
            "void_reasons": [{"reason": "duplicate", "count": 1}],
        },
        "money": {
            "billed_cents": 120_000,
            "collected_cents": 90_000,
            "outstanding_cents": 30_000,
            "collection_rate": 0.75,
        },
        "autopay_run": {
            "charge_on": "2026-09-08",
            "charge_on_varies": False,
            "has_run": True,
            "scheduled": {"count": 7, "cents": 70_000},
            "succeeded": {"count": 5, "cents": 50_000},
            "failed": {"count": 1, "cents": 10_000},
            "pending": {"count": 1, "cents": 10_000},
        },
        "odd": [
            {
                "code": "invoice_without_enrollment",
                "label": "Invoice with no enrollment",
                "count": 1,
                "items": [
                    {
                        "kind": "invoice",
                        "id": "inv-1",
                        "label": "INV-1",
                        "href": "/admin/families/par-1",
                    }
                ],
            },
            {"code": "paused_family_invoiced", "label": "Paused", "count": 0, "items": []},
            {"code": "autopay_no_card", "label": "No card", "count": 0, "items": []},
            {"code": "autopay_on_dead_enrollment", "label": "Dead", "count": 0, "items": []},
        ],
        "tuition_discounts": {
            "gross_cents": 120_000,
            "discount_cents": 5_000,
            "net_cents": 115_000,
            "by_category": [{"category": "sibling", "amount_cents": 5_000}],
        },
        "warnings": ["attempts_unavailable"],
        # Extra key the view must tolerate (``extra="ignore"``).
        "internal_debug_marker": True,
    }


class FakeMonthCloseReader:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    async def build(self, period: str | None = None) -> dict[str, Any]:
        self.calls.append(period)
        return _view(period or "2026-09")


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _make_app(role: str, reader: FakeMonthCloseReader | None) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_month_close] = lambda: reader
    return app


@pytest.fixture
def reader() -> FakeMonthCloseReader:
    return FakeMonthCloseReader()


@pytest.fixture
def owner(reader: FakeMonthCloseReader) -> Iterator[TestClient]:
    with TestClient(_make_app("owner", reader)) as client:
        yield client


def test_owner_gets_the_month_close_view(owner: TestClient, reader: FakeMonthCloseReader) -> None:
    resp = owner.get("/api/v2/admin/reports/month-close?period=2026-09")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "2026-09"
    assert body["invoices"]["emailed"] + body["invoices"]["autopay_notices"] == 11
    assert body["money"]["collection_rate"] == 0.75
    assert body["autopay_run"]["failed"] == {"count": 1, "cents": 10_000}
    assert [row["code"] for row in body["odd"]] == [
        "invoice_without_enrollment",
        "paused_family_invoiced",
        "autopay_no_card",
        "autopay_on_dead_enrollment",
    ]
    assert body["tuition_discounts"]["net_cents"] == 115_000
    assert body["warnings"] == ["attempts_unavailable"]
    assert "internal_debug_marker" not in body
    assert reader.calls == ["2026-09"]


@pytest.mark.parametrize("role", ["admin", "coach", "parent"])
def test_every_non_owner_persona_is_404(role: str, reader: FakeMonthCloseReader) -> None:
    """Owner-only, and it 404s rather than 403s so nothing is leaked."""
    with TestClient(_make_app(role, reader)) as client:
        resp = client.get("/api/v2/admin/reports/month-close")

    assert resp.status_code == 404
    assert reader.calls == []


def test_bad_period_is_422(owner: TestClient, reader: FakeMonthCloseReader) -> None:
    resp = owner.get("/api/v2/admin/reports/month-close?period=2026-13")

    assert resp.status_code == 422
    assert reader.calls == []


def test_no_period_passes_none_to_the_reader(
    owner: TestClient, reader: FakeMonthCloseReader
) -> None:
    resp = owner.get("/api/v2/admin/reports/month-close")

    assert resp.status_code == 200, resp.text
    assert reader.calls == [None]


def test_an_unwired_reader_is_503_not_a_crash() -> None:
    with TestClient(_make_app("owner", None)) as client:
        resp = client.get("/api/v2/admin/reports/month-close")

    assert resp.status_code == 503


def test_a_null_collection_rate_and_no_discounts_still_serialise(
    owner: TestClient, reader: FakeMonthCloseReader
) -> None:
    """An empty month: the rate is null (rendered "—") and the card is absent."""

    async def empty(period: str | None = None) -> dict[str, Any]:
        view = _view(period or "2026-09")
        view["money"] = {
            "billed_cents": 0,
            "collected_cents": 0,
            "outstanding_cents": 0,
            "collection_rate": None,
        }
        view["tuition_discounts"] = None
        view["warnings"] = []
        return view

    reader.build = empty  # type: ignore[method-assign]

    resp = owner.get("/api/v2/admin/reports/month-close?period=2026-09")

    assert resp.status_code == 200, resp.text
    assert resp.json()["money"]["collection_rate"] is None
    assert resp.json()["tuition_discounts"] is None
