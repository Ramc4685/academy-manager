"""Interface tests for GET/POST /admin/payroll/{month}/... routes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.finance.application.use_cases.bulk_payroll import (
    BulkGenerateResult,
    BulkRecomputeResult,
)
from backend.v2.contexts.finance.application.use_cases.list_monthly_payroll import (
    MonthlyPayrollRow,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import AdminUserSummary
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

# ---------------------------------------------------------------------------
# Minimal fakes
# ---------------------------------------------------------------------------


class _FakeListMonthlyPayroll:
    def __init__(self, rows: list[MonthlyPayrollRow]) -> None:
        self._rows = rows

    async def execute(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list[MonthlyPayrollRow]:
        return self._rows


class _FakeBulkGeneratePayroll:
    async def execute(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> BulkGenerateResult:
        return BulkGenerateResult(generated=2, skipped=1)


class _FakeBulkRecomputePayroll:
    async def execute(
        self,
        *,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
        actor_id: str,
    ) -> BulkRecomputeResult:
        return BulkRecomputeResult(recomputed=2, skipped=0)


# ---------------------------------------------------------------------------
# Minimal AdminUseCases with only payroll fields wired
# ---------------------------------------------------------------------------


def _minimal_admin_use_cases(
    list_admin_users=None,
    list_monthly_payroll=None,
    bulk_generate_payroll=None,
    bulk_recompute_payroll=None,
) -> AdminUseCases:
    """Build the smallest possible AdminUseCases for payroll route tests."""
    mock = AsyncMock(return_value=[])
    list_admin_users = list_admin_users or mock
    return AdminUseCases(
        list_admin_users=list_admin_users,  # type: ignore[arg-type]
        list_admin_students=mock,  # type: ignore[arg-type]
        create_session=mock,  # type: ignore[arg-type]
        edit_session=mock,  # type: ignore[arg-type]
        cancel_session=mock,  # type: ignore[arg-type]
        edit_roster_add=mock,  # type: ignore[arg-type]
        cancel_enrollment=mock,  # type: ignore[arg-type]
        transfer_enrollment=mock,  # type: ignore[arg-type]
        override_enrollment_fee=mock,  # type: ignore[arg-type]
        pause_enrollment=mock,  # type: ignore[arg-type]
        resume_enrollment=mock,  # type: ignore[arg-type]
        withdraw_enrollment=mock,  # type: ignore[arg-type]
        join_waitlist=mock,  # type: ignore[arg-type]
        promote_from_waitlist=mock,  # type: ignore[arg-type]
        skip_from_waitlist=mock,  # type: ignore[arg-type]
        remove_from_waitlist=mock,  # type: ignore[arg-type]
        list_admin_pause_requests=mock,  # type: ignore[arg-type]
        approve_pause_request=mock,  # type: ignore[arg-type]
        decline_pause_request=mock,  # type: ignore[arg-type]
        issue_refund=mock,  # type: ignore[arg-type]
        quote_enrollment=mock,
        preview_withdrawal_credit=mock,  # type: ignore[arg-type]
        approve_withdrawal_credit=mock,  # type: ignore[arg-type]
        list_payments_recent=mock,
        list_billing_invoices=mock,
        get_billing_invoice_detail=mock,
        generate_billing_invoice_artifact=mock,
        generate_monthly_payments=mock,  # type: ignore[arg-type]
        mark_payment_paid=mock,  # type: ignore[arg-type]
        apply_payment_discount=mock,  # type: ignore[arg-type]
        undo_payment_paid=mock,  # type: ignore[arg-type]
        record_expense=mock,  # type: ignore[arg-type]
        edit_expense=mock,  # type: ignore[arg-type]
        delete_expense=mock,  # type: ignore[arg-type]
        expenses=mock,  # type: ignore[arg-type]
        payouts=mock,  # type: ignore[arg-type]
        revenue_query=mock,  # type: ignore[arg-type]
        list_admin_sessions=mock,
        list_session_occurrences=mock,
        update_session_occurrence_coach=mock,
        mark_coach_attendance=mock,  # type: ignore[arg-type]
        list_admin_enrollments_for_session=mock,
        list_waitlist_for_session=mock,
        list_audit_logs=mock,
        list_dues_followup=mock,
        send_dues_reminders=mock,  # type: ignore[arg-type]
        export_report_csv=mock,
        get_reports_kpis=mock,
        list_enrollment_events=mock,
        comms=mock,  # type: ignore[arg-type]
        list_admin_waivers=mock,  # type: ignore[arg-type]
        get_academy_use_case=mock,  # type: ignore[arg-type]
        update_academy_use_case=mock,  # type: ignore[arg-type]
        get_academy_fees_use_case=mock,  # type: ignore[arg-type]
        update_academy_fees_use_case=mock,  # type: ignore[arg-type]
        get_academy_notifications_use_case=mock,  # type: ignore[arg-type]
        update_academy_notifications_use_case=mock,  # type: ignore[arg-type]
        get_academy_gateway_use_case=mock,  # type: ignore[arg-type]
        change_user_role=mock,  # type: ignore[arg-type]
        list_monthly_payroll=list_monthly_payroll,
        bulk_generate_payroll=bulk_generate_payroll,
        bulk_recompute_payroll=bulk_recompute_payroll,
    )


def _admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="adm-1",
        email="admin@example.com",
        academy_id="acad",
        roles=("admin",),
    )


def _make_app(use_cases: AdminUseCases) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _admin_claims()
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    return app


@pytest.fixture()
def payroll_client() -> Iterator[TestClient]:
    """Client with payroll use cases fully wired."""
    rows = [
        MonthlyPayrollRow(
            coach_id="coach-1",
            session_count=4,
            total_minor=20000,
            currency="USD",
            status="not_generated",
            period_id=None,
            warning_count=0,
            warning_status="clear",
        ),
        MonthlyPayrollRow(
            coach_id="coach-2",
            session_count=2,
            total_minor=10000,
            currency="USD",
            status="draft",
            period_id="pp-abc",
            warning_count=1,
            warning_status="unresolved",
        ),
    ]
    uc = _minimal_admin_use_cases(
        list_admin_users=AsyncMock(
            execute=AsyncMock(
                return_value=[
                    AdminUserSummary(
                        user_id="coach-1",
                        email="coach1@example.com",
                        display_name="Coach One",
                        role="coach",
                        status="active",
                    ),
                    AdminUserSummary(
                        user_id="coach-2",
                        email="coach2@example.com",
                        display_name="Coach Two",
                        role="coach",
                        status="active",
                    ),
                ]
            )
        ),
        list_monthly_payroll=_FakeListMonthlyPayroll(rows),
        bulk_generate_payroll=_FakeBulkGeneratePayroll(),
        bulk_recompute_payroll=_FakeBulkRecomputePayroll(),
    )
    with TestClient(_make_app(uc)) as client:
        yield client


@pytest.fixture()
def unconfigured_client() -> Iterator[TestClient]:
    """Client with payroll use cases NOT wired (returns 503)."""
    uc = _minimal_admin_use_cases()
    with TestClient(_make_app(uc)) as client:
        yield client


# ---------------------------------------------------------------------------
# Validation tests (month parsing) — 422 on bad input
# ---------------------------------------------------------------------------


def test_get_monthly_payroll_rejects_month_13(unconfigured_client) -> None:
    r = unconfigured_client.get("/api/v2/admin/payroll/2026-13")
    assert r.status_code == 422


def test_get_monthly_payroll_rejects_non_numeric(unconfigured_client) -> None:
    r = unconfigured_client.get("/api/v2/admin/payroll/june")
    assert r.status_code == 422


def test_generate_rejects_bad_month(unconfigured_client) -> None:
    r = unconfigured_client.post("/api/v2/admin/payroll/bad-month/generate")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 503 when use cases not configured
# ---------------------------------------------------------------------------


def test_get_monthly_payroll_503_when_not_configured(unconfigured_client) -> None:
    r = unconfigured_client.get("/api/v2/admin/payroll/2026-06")
    assert r.status_code == 503


def test_generate_503_when_not_configured(unconfigured_client) -> None:
    r = unconfigured_client.post("/api/v2/admin/payroll/2026-06/generate")
    assert r.status_code == 503


def test_recompute_503_when_not_configured(unconfigured_client) -> None:
    r = unconfigured_client.post("/api/v2/admin/payroll/2026-06/recompute")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# Happy-path tests with wired fakes
# ---------------------------------------------------------------------------


def test_get_monthly_payroll_returns_200(payroll_client) -> None:
    resp = payroll_client.get("/api/v2/admin/payroll/2026-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-06"
    assert isinstance(body["rows"], list)
    assert len(body["rows"]) == 2
    assert body["rows"][0]["coach_name"] == "Coach One"
    assert body["rows"][1]["coach_name"] == "Coach Two"
    assert body["rows"][0]["warning_count"] == 0
    assert body["rows"][0]["warning_status"] == "clear"
    assert body["rows"][1]["warning_count"] == 1
    assert body["rows"][1]["warning_status"] == "unresolved"
    assert body["total_amount_cents"] == sum(r["total_amount_cents"] for r in body["rows"])
    assert body["total_amount_cents"] == 30000


def test_get_monthly_payroll_december_wraps_year(payroll_client) -> None:
    """Month 12 end window must be Jan 1 of next year, not month 13."""
    resp = payroll_client.get("/api/v2/admin/payroll/2026-12")
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-12"
    assert body["period_end"].startswith("2027-01-01")


def test_bulk_generate_returns_result(payroll_client) -> None:
    resp = payroll_client.post("/api/v2/admin/payroll/2026-06/generate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-06"
    assert body["generated"] == 2
    assert body["skipped"] == 1


def test_bulk_recompute_returns_result(payroll_client) -> None:
    resp = payroll_client.post("/api/v2/admin/payroll/2026-06/recompute")
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-06"
    assert body["recomputed"] == 2
    assert body["skipped"] == 0
