"""Phase-3 admin financial report composition tests (refunds, revenue by category,
deposit slip, QuickBooks export)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pytest

import backend.v2.contexts.billing.infrastructure.admin_reports_read_model as reports_read_model
from backend.v2.shared.tenancy.context import tenant_scope


def _db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    return client["test_db"]


@pytest.mark.asyncio
async def test_refunds_report_lists_audit_refunds_and_credits_with_tenant_isolation() -> None:
    db = _db()
    await db["billing_audit_log"].insert_many(
        [
            {
                "audit_id": "baud-1",
                "academy_id": "acad",
                "action": "refund_issued",
                "actor_id": "admin-1",
                "at": datetime(2026, 5, 10, 15, 0, tzinfo=UTC),
                "invoice_id": "inv-1",
                "payment_id": "lpay-1",
                "reason": "duplicate charge",
                "before": {"refunded_cents": 0},
                "after": {"refunded_cents": 2_500},
            },
            {
                "audit_id": "baud-2",
                "academy_id": "acad",
                "action": "refund_issued",
                "actor_id": "admin-1",
                "at": datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
                "invoice_id": "inv-2",
                "payment_id": "lpay-2",
                "reason": "class cancelled",
                "before": {"refunded_cents": 1_000},
                "after": {"refunded_cents": 2_000},
            },
            {
                # other month — excluded
                "audit_id": "baud-other-month",
                "academy_id": "acad",
                "action": "refund_issued",
                "actor_id": "admin-1",
                "at": datetime(2026, 4, 20, tzinfo=UTC),
                "invoice_id": "inv-1",
                "before": {"refunded_cents": 0},
                "after": {"refunded_cents": 9_900},
            },
            {
                # other action — excluded
                "audit_id": "baud-manual",
                "academy_id": "acad",
                "action": "manual_payment_recorded",
                "actor_id": "admin-1",
                "at": datetime(2026, 5, 12, tzinfo=UTC),
                "invoice_id": "inv-1",
            },
            {
                # other tenant — excluded
                "audit_id": "baud-other-tenant",
                "academy_id": "other",
                "action": "refund_issued",
                "actor_id": "admin-9",
                "at": datetime(2026, 5, 11, tzinfo=UTC),
                "invoice_id": "inv-x",
                "before": {"refunded_cents": 0},
                "after": {"refunded_cents": 7_700},
            },
        ]
    )
    await db["invoices"].insert_many(
        [
            {
                "invoice_id": "inv-1",
                "academy_id": "acad",
                "invoice_number": "BLNO-202605-001",
                "parent_id": "parent-1",
                "student_id": "student-1",
            },
            {
                "invoice_id": "inv-2",
                "academy_id": "acad",
                "invoice_number": "BLNO-202605-002",
                "parent_id": "parent-2",
                "student_id": "student-2",
            },
        ]
    )
    await db["account_credit_ledger"].insert_many(
        [
            {
                "credit_id": "cred-1",
                "academy_id": "acad",
                "parent_id": "parent-1",
                "type": "withdrawal_credit",
                "status": "approved",
                "amount_cents": 1_500,
                "remaining_amount_cents": 1_500,
                "reason": "mid-month withdrawal",
                "created_at": datetime(2026, 5, 18, tzinfo=UTC),
            },
            {
                # other tenant — excluded
                "credit_id": "cred-other",
                "academy_id": "other",
                "parent_id": "parent-x",
                "amount_cents": 9_900,
                "remaining_amount_cents": 9_900,
                "reason": "x",
                "created_at": datetime(2026, 5, 18, tzinfo=UTC),
            },
            {
                # other month — excluded
                "credit_id": "cred-old",
                "academy_id": "acad",
                "parent_id": "parent-1",
                "amount_cents": 9_900,
                "remaining_amount_cents": 0,
                "reason": "old",
                "created_at": datetime(2026, 4, 2, tzinfo=UTC),
            },
        ]
    )

    with tenant_scope("acad"):
        report = await reports_read_model.make_refunds_report(db)("2026-05")

    assert report["period"] == "2026-05"
    assert report["total_refunded_cents"] == 3_500
    assert report["refund_count"] == 2
    # newest first
    assert [row["invoice_id"] for row in report["refunds"]] == ["inv-2", "inv-1"]
    first = report["refunds"][0]
    assert first["amount_cents"] == 1_000
    assert first["invoice_number"] == "BLNO-202605-002"
    assert first["parent_id"] == "parent-2"
    assert first["student_id"] == "student-2"
    assert first["reason"] == "class cancelled"
    assert report["total_credit_cents"] == 1_500
    assert report["credit_count"] == 1
    assert report["credits"][0]["credit_id"] == "cred-1"


@pytest.mark.asyncio
async def test_revenue_by_category_prorates_allocations_across_invoice_lines() -> None:
    db = _db()
    await db["payment_allocations"].insert_many(
        [
            {
                "allocation_id": "alloc-1",
                "academy_id": "acad",
                "payment_id": "lpay-1",
                "invoice_id": "inv-1",
                "amount_cents": 10_000,
                "created_at": datetime(2026, 5, 5, tzinfo=UTC),
            },
            {
                # partial payment allocation to invoice with tuition+fee lines
                "allocation_id": "alloc-2",
                "academy_id": "acad",
                "payment_id": "lpay-2",
                "invoice_id": "inv-2",
                "amount_cents": 5_000,
                "created_at": datetime(2026, 5, 6, tzinfo=UTC),
            },
            {
                # invoice without lines → uncategorized
                "allocation_id": "alloc-3",
                "academy_id": "acad",
                "payment_id": "lpay-3",
                "invoice_id": "inv-nolines",
                "amount_cents": 2_000,
                "created_at": datetime(2026, 5, 7, tzinfo=UTC),
            },
            {
                # other month — excluded
                "allocation_id": "alloc-old",
                "academy_id": "acad",
                "payment_id": "lpay-4",
                "invoice_id": "inv-1",
                "amount_cents": 99_000,
                "created_at": datetime(2026, 4, 7, tzinfo=UTC),
            },
            {
                # other tenant — excluded
                "allocation_id": "alloc-other",
                "academy_id": "other",
                "payment_id": "lpay-5",
                "invoice_id": "inv-1",
                "amount_cents": 99_000,
                "created_at": datetime(2026, 5, 7, tzinfo=UTC),
            },
        ]
    )
    await db["invoice_lines"].insert_many(
        [
            {
                "line_id": "line-1",
                "academy_id": "acad",
                "invoice_id": "inv-1",
                "line_type": "tuition",
                "category": "tuition",
                "category_label": "Tuition",
                "amount_cents": 10_000,
            },
            # inv-2: 9000 tuition + 1000 registration fee; 5000 allocated →
            # 4500 tuition + 500 fee
            {
                "line_id": "line-2",
                "academy_id": "acad",
                "invoice_id": "inv-2",
                "line_type": "tuition",
                "category": "tuition",
                "category_label": "Tuition",
                "amount_cents": 9_000,
            },
            {
                "line_id": "line-3",
                "academy_id": "acad",
                "invoice_id": "inv-2",
                "line_type": "fee",
                "category": "registration_fee",
                "category_label": "Registration fee",
                "amount_cents": 1_000,
            },
            {
                # negative discount line must not receive allocation
                "line_id": "line-4",
                "academy_id": "acad",
                "invoice_id": "inv-2",
                "line_type": "discount",
                "category": "sibling_discount",
                "amount_cents": -500,
            },
        ]
    )
    await db["ledger_payments"].insert_one(
        {
            "payment_id": "lpay-unapplied",
            "academy_id": "acad",
            "status": "succeeded",
            "amount_cents": 3_000,
            "unapplied_amount_cents": 3_000,
            "paid_at": datetime(2026, 5, 9, tzinfo=UTC),
            "created_at": datetime(2026, 5, 9, tzinfo=UTC),
        }
    )

    with tenant_scope("acad"):
        report = await reports_read_model.make_revenue_by_category_report(db)("2026-05")

    assert report["period"] == "2026-05"
    assert report["total_allocated_cents"] == 17_000
    assert report["unapplied_cents"] == 3_000
    rows = {row["category"]: row for row in report["rows"]}
    assert rows["tuition"]["amount_cents"] == 14_500
    assert rows["tuition"]["category_label"] == "Tuition"
    assert rows["registration_fee"]["amount_cents"] == 500
    assert rows["uncategorized"]["amount_cents"] == 2_000
    # rows sorted by amount desc
    assert [row["category"] for row in report["rows"]] == [
        "tuition",
        "uncategorized",
        "registration_fee",
    ]


@pytest.mark.asyncio
async def test_deposit_slip_groups_payments_by_day_and_method() -> None:
    db = _db()
    await db["ledger_payments"].insert_many(
        [
            {
                "payment_id": "lpay-1",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 10_000,
                "payment_method": "card",
                "paid_at": datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
                "created_at": datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
            },
            {
                "payment_id": "lpay-2",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 4_000,
                "payment_method": "card",
                "paid_at": datetime(2026, 5, 4, 16, 0, tzinfo=UTC),
                "created_at": datetime(2026, 5, 4, 16, 0, tzinfo=UTC),
            },
            {
                "payment_id": "lpay-3",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 2_500,
                "payment_method": "cash",
                "paid_at": datetime(2026, 5, 4, 17, 0, tzinfo=UTC),
                "created_at": datetime(2026, 5, 4, 17, 0, tzinfo=UTC),
            },
            {
                # falls back to created_at when paid_at missing
                "payment_id": "lpay-4",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 6_000,
                "created_at": datetime(2026, 5, 12, tzinfo=UTC),
            },
            {
                # failed payment — excluded
                "payment_id": "lpay-failed",
                "academy_id": "acad",
                "status": "failed",
                "amount_cents": 9_900,
                "paid_at": datetime(2026, 5, 4, tzinfo=UTC),
                "created_at": datetime(2026, 5, 4, tzinfo=UTC),
            },
            {
                # other month — excluded
                "payment_id": "lpay-old",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 9_900,
                "paid_at": datetime(2026, 4, 4, tzinfo=UTC),
                "created_at": datetime(2026, 4, 4, tzinfo=UTC),
            },
            {
                # other tenant — excluded
                "payment_id": "lpay-other",
                "academy_id": "other",
                "status": "succeeded",
                "amount_cents": 9_900,
                "paid_at": datetime(2026, 5, 4, tzinfo=UTC),
                "created_at": datetime(2026, 5, 4, tzinfo=UTC),
            },
        ]
    )

    with tenant_scope("acad"):
        report = await reports_read_model.make_deposit_slip_report(db)("2026-05")

    assert report["period"] == "2026-05"
    assert report["total_cents"] == 22_500
    assert report["count"] == 4
    assert [day["date"] for day in report["days"]] == ["2026-05-04", "2026-05-12"]
    first_day = report["days"][0]
    assert first_day["total_cents"] == 16_500
    assert first_day["count"] == 3
    assert first_day["methods"] == [
        {"method": "card", "amount_cents": 14_000, "count": 2},
        {"method": "cash", "amount_cents": 2_500, "count": 1},
    ]
    second_day = report["days"][1]
    assert second_day["methods"] == [{"method": "unknown", "amount_cents": 6_000, "count": 1}]


@pytest.mark.asyncio
async def test_quickbooks_export_emits_balanced_journal_entries() -> None:
    db = _db()
    await db["ledger_payments"].insert_one(
        {
            "payment_id": "lpay-1",
            "academy_id": "acad",
            "status": "succeeded",
            "amount_cents": 12_000,
            "unapplied_amount_cents": 2_000,
            "payment_method": "card",
            "paid_at": datetime(2026, 5, 4, tzinfo=UTC),
            "created_at": datetime(2026, 5, 4, tzinfo=UTC),
        }
    )
    await db["payment_allocations"].insert_one(
        {
            "allocation_id": "alloc-1",
            "academy_id": "acad",
            "payment_id": "lpay-1",
            "invoice_id": "inv-1",
            "amount_cents": 10_000,
            "created_at": datetime(2026, 5, 4, tzinfo=UTC),
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "line_id": "line-1",
            "academy_id": "acad",
            "invoice_id": "inv-1",
            "line_type": "tuition",
            "category": "tuition",
            "category_label": "Tuition",
            "amount_cents": 10_000,
        }
    )
    await db["billing_audit_log"].insert_one(
        {
            "audit_id": "baud-1",
            "academy_id": "acad",
            "action": "refund_issued",
            "actor_id": "admin-1",
            "at": datetime(2026, 5, 10, tzinfo=UTC),
            "invoice_id": "inv-1",
            "before": {"refunded_cents": 0},
            "after": {"refunded_cents": 1_500},
        }
    )

    with tenant_scope("acad"):
        csv_text = await reports_read_model.make_financial_report_csv(db)("quickbooks", "2026-05")

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == ["JournalNo", "JournalDate", "Memo", "Account", "Debits", "Credits"]
    body = rows[1:]
    assert all(row[1] == "05/31/2026" for row in body)
    # every journal entry balances: total debits == total credits
    for journal_no in {row[0] for row in body}:
        entry = [row for row in body if row[0] == journal_no]
        debits = sum(float(row[4]) for row in entry if row[4])
        credits = sum(float(row[5]) for row in entry if row[5])
        assert debits == pytest.approx(credits), journal_no
    rev = [row for row in body if row[0] == "2026-05-REV"]
    assert [
        "2026-05-REV",
        "05/31/2026",
        "2026-05 payments received",
        "Undeposited Funds",
        "120.00",
        "",
    ] in rev
    assert any(row[3] == "Income:Tuition" and row[5] == "100.00" for row in rev)
    assert any(row[3] == "Unapplied Customer Payments" and row[5] == "20.00" for row in rev)
    ref = [row for row in body if row[0] == "2026-05-REF"]
    assert any(row[3] == "Refunds Given" and row[4] == "15.00" for row in ref)
    assert any(row[3] == "Undeposited Funds" and row[5] == "15.00" for row in ref)


@pytest.mark.asyncio
async def test_financial_report_csv_returns_none_for_legacy_reports() -> None:
    db = _db()
    with tenant_scope("acad"):
        renderer = reports_read_model.make_financial_report_csv(db)
        assert await renderer("revenue", "2026-05") is None
        assert await renderer("pending-payments", None) is None


@pytest.mark.asyncio
async def test_refunds_and_deposit_slip_csv_render_rows() -> None:
    db = _db()
    await db["billing_audit_log"].insert_one(
        {
            "audit_id": "baud-1",
            "academy_id": "acad",
            "action": "refund_issued",
            "actor_id": "admin-1",
            "at": datetime(2026, 5, 10, tzinfo=UTC),
            "invoice_id": "inv-1",
            "payment_id": "lpay-1",
            "reason": "duplicate",
            "before": {"refunded_cents": 0},
            "after": {"refunded_cents": 2_500},
        }
    )
    await db["ledger_payments"].insert_one(
        {
            "payment_id": "lpay-1",
            "academy_id": "acad",
            "status": "succeeded",
            "amount_cents": 5_000,
            "payment_method": "cash",
            "paid_at": datetime(2026, 5, 4, tzinfo=UTC),
            "created_at": datetime(2026, 5, 4, tzinfo=UTC),
        }
    )

    with tenant_scope("acad"):
        renderer = reports_read_model.make_financial_report_csv(db)
        refunds_csv = await renderer("refunds", "2026-05")
        deposit_csv = await renderer("deposit-slip", "2026-05")

    refund_rows = list(csv.reader(io.StringIO(refunds_csv)))
    assert refund_rows[0][0] == "type"
    assert refund_rows[1][0] == "refund"
    assert refund_rows[1][7] == "2500"

    deposit_rows = list(csv.reader(io.StringIO(deposit_csv)))
    assert deposit_rows[0] == ["date", "method", "count", "amount_cents"]
    assert deposit_rows[1] == ["2026-05-04", "cash", "1", "5000"]


@pytest.mark.asyncio
async def test_csv_export_neutralises_formula_injection_in_free_text() -> None:
    db = _db()
    await db["billing_audit_log"].insert_one(
        {
            "audit_id": "baud-1",
            "academy_id": "acad",
            "action": "refund_issued",
            "actor_id": "admin-1",
            "at": datetime(2026, 5, 10, tzinfo=UTC),
            "invoice_id": "inv-1",
            "payment_id": "lpay-1",
            "reason": '=HYPERLINK("http://evil.example")',
            "before": {"refunded_cents": 0},
            "after": {"refunded_cents": 2_500},
        }
    )

    with tenant_scope("acad"):
        refunds_csv = await reports_read_model.make_financial_report_csv(db)("refunds", "2026-05")

    refund_rows = list(csv.reader(io.StringIO(refunds_csv)))
    assert refund_rows[1][8].startswith("'=")
