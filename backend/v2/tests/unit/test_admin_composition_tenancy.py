"""Admin composition tenant-scope hardening tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy.context import tenant_scope


class _NoopStripe:
    pass


def _admin_use_cases(db: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_NoopStripe(),  # type: ignore[arg-type]
    )


@pytest.fixture
def mongo_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_DEFAULT_ACADEMY_ID", raising=False)
    monkeypatch.delenv("DEFAULT_ACADEMY_ID", raising=False)
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_audit_logs_use_request_tenant_not_default(mongo_db) -> None:
    await mongo_db["audit_logs"].insert_many(
        [
            {
                "audit_id": "audit-request",
                "academy_id": "request-acad",
                "actor_id": "admin-1",
                "action": "billing.viewed",
                "entity_type": "invoice",
                "entity_id": "inv-1",
                "created_at": datetime(2026, 6, 16, tzinfo=UTC),
            },
            {
                "audit_id": "audit-default",
                "academy_id": "default-academy",
                "actor_id": "admin-2",
                "action": "billing.viewed",
                "entity_type": "invoice",
                "entity_id": "inv-2",
                "created_at": datetime(2026, 6, 15, tzinfo=UTC),
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_audit_logs()

    assert [row["audit_id"] for row in rows] == ["audit-request"]


@pytest.mark.asyncio
async def test_admin_invoice_detail_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["invoices"].insert_many(
        [
            {
                "invoice_id": "inv-shared",
                "invoice_number": "REQ-001",
                "academy_id": "request-acad",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "enrollment_id": "enr-1",
                "period": "2026-06",
                "status": "open",
                "total_cents": 10000,
                "balance_due_cents": 4000,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
            {
                "invoice_id": "inv-shared",
                "invoice_number": "DEFAULT-001",
                "academy_id": "default-academy",
                "parent_id": "parent-2",
                "student_id": "student-2",
                "enrollment_id": "enr-2",
                "period": "2026-06",
                "status": "open",
                "total_cents": 99999,
                "balance_due_cents": 99999,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )
    await mongo_db["invoice_lines"].insert_one(
        {
            "line_id": "line-request",
            "academy_id": "request-acad",
            "invoice_id": "inv-shared",
            "description": "Request academy tuition",
            "amount_cents": 10000,
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        detail = await admin.get_billing_invoice_detail("inv-shared")

    assert detail["invoice_number"] == "REQ-001"
    assert detail["due_amount_cents"] == 4000
    assert detail["lines"] == [{"description": "Request academy tuition", "amount_cents": 10000}]


@pytest.mark.asyncio
async def test_admin_invoice_detail_payment_fallback_uses_request_tenant(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-shared",
                "invoice_number": "REQ-PAY-001",
                "academy_id": "request-acad",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "period": "2026-06",
                "status": "pending",
                "amount_cents": 12000,
                "paid_amount_cents": 2000,
                "balance_due_cents": 10000,
                "created_at": now,
            },
            {
                "payment_id": "pay-shared",
                "invoice_number": "DEFAULT-PAY-001",
                "academy_id": "default-academy",
                "parent_id": "parent-2",
                "student_id": "student-2",
                "period": "2026-06",
                "status": "succeeded",
                "amount_cents": 99999,
                "paid_amount_cents": 99999,
                "balance_due_cents": 0,
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        detail = await admin.get_billing_invoice_detail("pay-shared")

    assert detail["invoice_number"] == "REQ-PAY-001"
    assert detail["due_amount_cents"] == 10000
    assert detail["paid_amount_cents"] == 2000


@pytest.mark.asyncio
async def test_admin_invoice_artifact_write_enforces_request_tenant_ownership(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["invoices"].insert_one(
        {
            "invoice_id": "inv-request",
            "invoice_number": "REQ-002",
            "academy_id": "request-acad",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enr-1",
            "period": "2026-06",
            "status": "open",
            "total_cents": 10000,
            "balance_due_cents": 4000,
            "currency": "usd",
            "due_date": now,
            "created_at": now,
            "updated_at": now,
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        result = await admin.generate_billing_invoice_artifact("inv-request", "invoice_pdf")

    artifact = await mongo_db["billing_artifacts"].find_one(
        {"academy_id": "request-acad", "artifact_id": result["artifact_id"]}
    )
    invoice = await mongo_db["invoices"].find_one(
        {"academy_id": "request-acad", "invoice_id": "inv-request"}
    )
    default_artifact = await mongo_db["billing_artifacts"].find_one(
        {"academy_id": "default-academy", "artifact_id": result["artifact_id"]}
    )

    assert artifact is not None
    assert default_artifact is None
    assert invoice is not None
    assert invoice["invoice_pdf_artifact_id"] == result["artifact_id"]


@pytest.mark.asyncio
async def test_admin_payment_artifact_write_enforces_request_tenant_ownership(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-shared",
                "invoice_number": "REQ-PAY-001",
                "academy_id": "request-acad",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "period": "2026-06",
                "status": "pending",
                "amount_cents": 10000,
                "created_at": now,
                "updated_at": now,
            },
            {
                "payment_id": "pay-shared",
                "invoice_number": "DEFAULT-PAY-001",
                "academy_id": "default-academy",
                "parent_id": "parent-2",
                "student_id": "student-2",
                "period": "2026-06",
                "status": "pending",
                "amount_cents": 99999,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        result = await admin.generate_billing_invoice_artifact("pay-shared", "receipt")

    artifact = await mongo_db["billing_artifacts"].find_one(
        {"academy_id": "request-acad", "artifact_id": result["artifact_id"]}
    )
    request_payment = await mongo_db["payments"].find_one(
        {"academy_id": "request-acad", "payment_id": "pay-shared"}
    )
    default_payment = await mongo_db["payments"].find_one(
        {"academy_id": "default-academy", "payment_id": "pay-shared"}
    )

    assert artifact is not None
    assert request_payment is not None
    assert request_payment["receipt_artifact_id"] == result["artifact_id"]
    assert default_payment is not None
    assert "receipt_artifact_id" not in default_payment


@pytest.mark.asyncio
async def test_admin_dues_followup_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-request",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "status": "pending",
                "amount_cents": 12000,
                "created_at": now,
            },
            {
                "payment_id": "pay-default",
                "academy_id": "default-academy",
                "parent_id": "parent-default",
                "student_id": "student-default",
                "status": "pending",
                "amount_cents": 99000,
                "created_at": now,
            },
        ]
    )
    await mongo_db["users"].insert_many(
        [
            {
                "academy_id": "request-acad",
                "user_id": "parent-request",
                "display_name": "Request Parent",
                "email": "request@example.com",
            },
            {
                "academy_id": "default-academy",
                "user_id": "parent-default",
                "display_name": "Default Parent",
                "email": "default@example.com",
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_dues_followup()

    assert [row["parent_id"] for row in rows] == ["parent-request"]
    assert rows[0]["parent_name"] == "Request Parent"
    assert rows[0]["total_due_cents"] == 12000


@pytest.mark.asyncio
async def test_admin_attendance_export_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["attendance"].insert_many(
        [
            {
                "attendance_id": "att-request",
                "academy_id": "request-acad",
                "session_id": "sess-request",
                "student_id": "student-request",
                "status": "present",
                "marked_at": now,
            },
            {
                "attendance_id": "att-default",
                "academy_id": "default-academy",
                "session_id": "sess-default",
                "student_id": "student-default",
                "status": "present",
                "marked_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        csv_text = await admin.export_report_csv("attendance")

    assert "att-request" in csv_text
    assert "att-default" not in csv_text


@pytest.mark.asyncio
async def test_admin_pending_payments_export_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-request",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "status": "pending",
                "amount_cents": 12000,
                "created_at": now,
            },
            {
                "payment_id": "pay-default",
                "academy_id": "default-academy",
                "parent_id": "parent-default",
                "student_id": "student-default",
                "status": "pending",
                "amount_cents": 99000,
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        csv_text = await admin.export_report_csv("pending-payments")

    assert "pay-request" in csv_text
    assert "pay-default" not in csv_text


@pytest.mark.asyncio
async def test_admin_report_export_rejects_unknown_report_name(mongo_db) -> None:
    admin = _admin_use_cases(mongo_db)

    with tenant_scope("request-acad"), pytest.raises(ValueError, match="unknown report export"):
        await admin.export_report_csv("all-tenants")


@pytest.mark.asyncio
async def test_admin_enrollment_funnel_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["onboarding_applications"].insert_many(
        [
            {
                "application_id": "app-request",
                "academy_id": "request-acad",
                "status": "APPROVED",
                "created_at": now,
            },
            {
                "application_id": "app-default",
                "academy_id": "default-academy",
                "status": "DRAFT",
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        result = await admin.get_enrollment_funnel(None)

    assert result.confirmed == 1
    assert result.leads == 0
