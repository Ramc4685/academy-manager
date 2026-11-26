"""S41: ``GET /admin/reports/invoices.csv`` and ``/admin/reports/aging.csv``.

Real renderer over mongomock: owner-only, formula cells neutralised, totals
equal the reports dashboard read model, and another academy's rows never leak.
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import backend.v2.contexts.billing.infrastructure.admin_reports_read_model as reports_read_model
from backend.v2.composition.report_exports import compose_report_exports
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import tenant_scope


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reports_read_model, "_now", lambda: datetime(2026, 12, 20, tzinfo=UTC))


def _invoice(invoice_id: str, *, academy: str = "acad", **extra: Any) -> dict[str, Any]:
    row = {
        "invoice_id": invoice_id,
        "invoice_number": f"INV-{invoice_id}",
        "academy_id": academy,
        "parent_id": f"parent-{invoice_id}",
        "period": "2026-11",
        "status": "open",
        "total_cents": 10_000,
        "balance_due_cents": 10_000,
        "currency": "usd",
        "created_at": datetime(2026, 11, 1, tzinfo=UTC),
        "due_date": datetime(2026, 11, 15, tzinfo=UTC),
    }
    row.update(extra)
    return row


def _seed(db: Any) -> None:
    async def go() -> None:
        await db["invoices"].insert_many(
            [
                _invoice("a", status="paid", balance_due_cents=0),
                _invoice("b", status="partially_paid", balance_due_cents=4_000),
                _invoice("c", invoice_number='=HYPERLINK("x")'),
                _invoice("void", status="void"),
                _invoice("other", academy="other-acad"),
            ]
        )
        await db["users"].insert_one(
            {"user_id": "parent-c", "academy_id": "acad", "display_name": "@Evil Parent"}
        )

    asyncio.run(go())


def _client(db: Any, roles: tuple[str, ...]) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    claims = AuthClaims(user_id="u-1", email="u@example.com", academy_id="acad", roles=roles)  # type: ignore[arg-type]
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_admin_use_cases] = lambda: object()
    renderer = compose_report_exports(db)

    async def scoped(report_name: str, period: str | None) -> str | None:
        with tenant_scope("acad"):
            return await renderer(report_name, period)  # type: ignore[operator]

    app.state.report_exports = scoped
    return TestClient(app)


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _dashboard(db: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        with tenant_scope("acad"):
            return await reports_read_model.make_reports_dashboard(db)("2026-11")  # type: ignore[operator]

    return asyncio.run(go())


def test_invoices_csv_totals_equal_the_dashboard_and_stay_in_tenant() -> None:
    db = AsyncMongoMockClient()["s41"]
    _seed(db)
    r = _client(db, ("owner",)).get(
        "/api/v2/admin/reports/invoices.csv", params={"period": "2026-11"}
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == 'attachment; filename="invoices-2026-11.csv"'
    rows = _rows(r.text)
    assert sorted(row["record_id"] for row in rows) == ["a", "b", "c"]
    dashboard = _dashboard(db)
    assert sum(int(row["billed_cents"]) for row in rows) == dashboard["billed_cents"]
    assert sum(int(row["outstanding_cents"]) for row in rows) == dashboard["outstanding_dues_cents"]


def test_aging_csv_matches_the_dashboard_buckets() -> None:
    db = AsyncMongoMockClient()["s41"]
    _seed(db)
    r = _client(db, ("owner",)).get("/api/v2/admin/reports/aging.csv", params={"period": "2026-11"})
    assert r.status_code == 200, r.text
    rows = _rows(r.text)
    by_bucket: dict[str, int] = {}
    for row in rows:
        by_bucket[row["bucket"]] = by_bucket.get(row["bucket"], 0) + int(row["outstanding_cents"])
    expected = {
        bucket["label"]: bucket["amount_cents"]
        for bucket in _dashboard(db)["collections_risk"]["aging_buckets"]
        if bucket["amount_cents"]
    }
    assert by_bucket == expected


def test_formula_leading_cells_are_neutralised() -> None:
    db = AsyncMongoMockClient()["s41"]
    _seed(db)
    client = _client(db, ("owner",))
    rows = _rows(client.get("/api/v2/admin/reports/invoices.csv?period=2026-11").text)
    c = next(row for row in rows if row["record_id"] == "c")
    assert c["invoice_number"].startswith("'=")
    assert c["family_name"] == "'@Evil Parent"


@pytest.mark.parametrize("report", ["invoices", "aging"])
def test_exports_are_owner_only(report: str) -> None:
    db = AsyncMongoMockClient()["s41"]
    _seed(db)
    r = _client(db, ("admin",)).get(f"/api/v2/admin/reports/{report}.csv?period=2026-11")
    assert r.status_code in (403, 404)
