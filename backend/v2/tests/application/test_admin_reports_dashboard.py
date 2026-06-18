"""Admin reports dashboard composition tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import backend.v2.composition.admin as admin_composition
from backend.v2.shared.tenancy.context import tenant_scope


@pytest.mark.asyncio
async def test_reports_dashboard_composes_monthly_finance_attendance_and_capacity() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]
    await db["payments"].insert_many(
        [
            {
                "payment_id": "pay-1",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 10_000,
                "refunded_cents": 1_000,
            },
            {
                "payment_id": "pay-2",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "partially_paid",
                "parent_id": "parent-1",
                "due_date": "2026-05-15",
                "amount_received_cents": 4_000,
                "balance_due_cents": 6_000,
                "final_amount_cents": 10_000,
            },
            {
                "payment_id": "pay-3",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "failed",
                "parent_id": "parent-2",
                "due_date": "2026-04-01",
                "final_amount_cents": 3_000,
            },
            {
                "payment_id": "pay-other-month",
                "academy_id": "acad",
                "period": "2026-04",
                "status": "succeeded",
                "final_amount_cents": 99_000,
            },
            {
                "payment_id": "pay-other-tenant",
                "academy_id": "other",
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 99_000,
            },
        ]
    )
    await db["expenses"].insert_many(
        [
            {
                "expense_id": "exp-1",
                "academy_id": "acad",
                "category": "rent",
                "amount_cents": 5_000,
                "incurred_on": datetime(2026, 5, 2, tzinfo=UTC),
            },
            {
                "expense_id": "exp-2",
                "academy_id": "acad",
                "category": "equipment",
                "amount_cents": 1_200,
                "incurred_on": datetime(2026, 5, 3, tzinfo=UTC),
            },
            {
                "expense_id": "exp-deleted",
                "academy_id": "acad",
                "category": "other",
                "amount_cents": 99_000,
                "incurred_on": datetime(2026, 5, 3, tzinfo=UTC),
                "deleted_at": datetime(2026, 5, 4, tzinfo=UTC),
            },
        ]
    )
    await db["attendance"].insert_many(
        [
            {
                "attendance_id": "att-1",
                "academy_id": "acad",
                "status": "present",
                "marked_at": datetime(2026, 5, 3, tzinfo=UTC),
            },
            {
                "attendance_id": "att-2",
                "academy_id": "acad",
                "status": "late",
                "marked_at": datetime(2026, 5, 4, tzinfo=UTC),
            },
            {
                "attendance_id": "att-3",
                "academy_id": "acad",
                "status": "absent",
                "marked_at": datetime(2026, 5, 5, tzinfo=UTC),
            },
            {
                "attendance_id": "att-other",
                "academy_id": "other",
                "status": "present",
                "marked_at": datetime(2026, 5, 6, tzinfo=UTC),
            },
        ]
    )
    await db["sessions"].insert_many(
        [
            {
                "session_id": "sess-1",
                "academy_id": "acad",
                "status": "scheduled",
                "capacity": 8,
                "start_at": datetime(2026, 5, 7, tzinfo=UTC),
            },
            {
                "session_id": "sess-2",
                "academy_id": "acad",
                "status": "completed",
                "capacity": 4,
                "start_at": datetime(2026, 5, 8, tzinfo=UTC),
            },
            {
                "session_id": "sess-3",
                "academy_id": "acad",
                "status": "cancelled",
                "capacity": 10,
                "start_at": datetime(2026, 5, 9, tzinfo=UTC),
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "enrollment_id": "enr-1",
                "academy_id": "acad",
                "session_id": "sess-1",
                "student_id": "st-1",
                "status": "active",
            },
            {
                "enrollment_id": "enr-2",
                "academy_id": "acad",
                "session_id": "sess-2",
                "student_id": "st-2",
                "status": "active",
            },
            {
                "enrollment_id": "enr-3",
                "academy_id": "acad",
                "session_id": "sess-2",
                "student_id": "st-3",
                "status": "paused",
            },
        ]
    )
    await db["waitlist"].insert_one(
        {
            "waitlist_id": "wait-1",
            "academy_id": "acad",
            "session_id": "sess-1",
            "status": "waiting",
        }
    )
    await db["payout_periods"].insert_many(
        [
            {
                "period_id": "pp-draft",
                "academy_id": "acad",
                "coach_id": "coach-1",
                "period_start": datetime(2026, 5, 1, tzinfo=UTC),
                "period_end": datetime(2026, 6, 1, tzinfo=UTC),
                "status": "draft",
                "total_minor": 4_000,
            },
            {
                "period_id": "pp-approved",
                "academy_id": "acad",
                "coach_id": "coach-2",
                "period_start": datetime(2026, 5, 1, tzinfo=UTC),
                "period_end": datetime(2026, 6, 1, tzinfo=UTC),
                "status": "approved",
                "total_minor": 6_000,
            },
            {
                "period_id": "pp-paid",
                "academy_id": "acad",
                "coach_id": "coach-3",
                "period_start": datetime(2026, 5, 1, tzinfo=UTC),
                "period_end": datetime(2026, 6, 1, tzinfo=UTC),
                "status": "paid",
                "total_minor": 3_000,
                "paid_amount_minor": 3_000,
            },
        ]
    )

    with tenant_scope("acad"):
        dashboard = await admin_composition._make_reports_dashboard(db)("2026-05")

    assert dashboard["period"] == "2026-05"
    assert dashboard["cash_collected_cents"] == 13_000
    assert dashboard["outstanding_dues_cents"] == 9_000
    assert dashboard["attendance"] == {
        "present_count": 2,
        "recorded_count": 3,
        "attendance_rate": 0.6667,
        "empty": False,
    }
    assert dashboard["sessions"] == {
        "scheduled_count": 1,
        "completed_count": 1,
        "cancelled_count": 1,
        "enrolled_seats": 2,
        "capacity": 12,
        "capacity_utilization": 0.1667,
        "waitlist_count": 1,
        "empty": False,
    }
    assert dashboard["expenses"] == {
        "total_cents": 6_200,
        "by_category": [
            {"category": "equipment", "amount_cents": 1_200, "count": 1},
            {"category": "rent", "amount_cents": 5_000, "count": 1},
        ],
    }
    assert dashboard["collections_risk"] == {
        "overdue_family_count": 2,
        "overdue_cents": 9_000,
        "failed_payment_count": 1,
        "partial_payment_count": 1,
        "aging_buckets": [
            {"label": "Current", "amount_cents": 0, "family_count": 0},
            {"label": "1-30", "amount_cents": 6_000, "family_count": 1},
            {"label": "31-60", "amount_cents": 0, "family_count": 0},
            {"label": "60+", "amount_cents": 3_000, "family_count": 1},
        ],
    }
    assert dashboard["profit_and_loss"] == {
        "revenue_cents": 13_000,
        "coach_payroll_cents": 9_000,
        "rent_cents": 5_000,
        "misc_expenses_cents": 1_200,
        "net_profit_cents": -2_200,
        "profit_margin": -0.1692,
    }
    assert dashboard["payroll"] == {
        "estimated_cents": 13_000,
        "approved_cents": 9_000,
        "paid_cents": 3_000,
        "unpaid_cents": 6_000,
        "blocked_by": None,
    }
    assert dashboard["empty_states"] == []


@pytest.mark.asyncio
async def test_reports_dashboard_uses_ledger_invoices_and_payments_without_legacy_payments() -> (
    None
):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]
    await db["invoices"].insert_many(
        [
            {
                "invoice_id": "inv-paid",
                "academy_id": "acad",
                "parent_id": "parent-paid",
                "period": "2026-05",
                "status": "paid",
                "total_cents": 10_000,
                "balance_due_cents": 0,
                "currency": "usd",
                "created_at": datetime(2026, 5, 3, tzinfo=UTC),
                "due_date": datetime(2026, 5, 15, tzinfo=UTC),
            },
            {
                "invoice_id": "inv-partial",
                "academy_id": "acad",
                "parent_id": "parent-partial",
                "period": "2026-05",
                "status": "partially_paid",
                "total_cents": 10_000,
                "balance_due_cents": 6_000,
                "currency": "usd",
                "created_at": datetime(2026, 5, 5, tzinfo=UTC),
                "due_date": datetime(2026, 5, 15, tzinfo=UTC),
            },
            {
                "invoice_id": "inv-failed",
                "academy_id": "acad",
                "parent_id": "parent-failed",
                "period": "2026-05",
                "status": "open",
                "total_cents": 3_000,
                "balance_due_cents": 3_000,
                "currency": "usd",
                "created_at": datetime(2026, 5, 6, tzinfo=UTC),
                "due_date": datetime(2026, 4, 1, tzinfo=UTC),
            },
        ]
    )
    await db["ledger_payments"].insert_many(
        [
            {
                "payment_id": "lp-paid",
                "academy_id": "acad",
                "parent_id": "parent-paid",
                "amount_cents": 9_000,
                "currency": "usd",
                "status": "succeeded",
                "created_at": datetime(2026, 5, 4, tzinfo=UTC),
            },
            {
                "payment_id": "lp-partial",
                "academy_id": "acad",
                "parent_id": "parent-partial",
                "amount_cents": 4_000,
                "currency": "usd",
                "status": "succeeded",
                "created_at": datetime(2026, 5, 7, tzinfo=UTC),
            },
        ]
    )
    await db["payment_attempts"].insert_one(
        {
            "attempt_id": "attempt-failed",
            "academy_id": "acad",
            "invoice_id": "inv-failed",
            "parent_id": "parent-failed",
            "amount_cents": 3_000,
            "currency": "usd",
            "status": "failed",
            "created_at": datetime(2026, 5, 8, tzinfo=UTC),
        }
    )

    with tenant_scope("acad"):
        dashboard = await admin_composition._make_reports_dashboard(db)("2026-05")

    assert dashboard["cash_collected_cents"] == 13_000
    assert dashboard["outstanding_dues_cents"] == 9_000
    assert dashboard["collections_risk"]["failed_payment_count"] == 1
    assert dashboard["collections_risk"]["partial_payment_count"] == 1
    assert dashboard["collections_risk"]["overdue_family_count"] == 2
    assert dashboard["collections_risk"]["aging_buckets"] == [
        {"label": "Current", "amount_cents": 0, "family_count": 0},
        {"label": "1-30", "amount_cents": 6_000, "family_count": 1},
        {"label": "31-60", "amount_cents": 0, "family_count": 0},
        {"label": "60+", "amount_cents": 3_000, "family_count": 1},
    ]


@pytest.mark.asyncio
async def test_reports_dashboard_returns_meaningful_empty_states() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]

    with tenant_scope("acad"):
        dashboard = await admin_composition._make_reports_dashboard(db)("2026-05")

    assert dashboard == {
        "period": "2026-05",
        "cash_collected_cents": 0,
        "outstanding_dues_cents": 0,
        "attendance": {
            "present_count": 0,
            "recorded_count": 0,
            "attendance_rate": None,
            "empty": True,
        },
        "sessions": {
            "scheduled_count": 0,
            "completed_count": 0,
            "cancelled_count": 0,
            "enrolled_seats": 0,
            "capacity": 0,
            "capacity_utilization": None,
            "waitlist_count": 0,
            "empty": True,
        },
        "expenses": {"total_cents": 0, "by_category": []},
        "collections_risk": {
            "overdue_family_count": 0,
            "overdue_cents": 0,
            "failed_payment_count": 0,
            "partial_payment_count": 0,
            "aging_buckets": [
                {"label": "Current", "amount_cents": 0, "family_count": 0},
                {"label": "1-30", "amount_cents": 0, "family_count": 0},
                {"label": "31-60", "amount_cents": 0, "family_count": 0},
                {"label": "60+", "amount_cents": 0, "family_count": 0},
            ],
        },
        "profit_and_loss": {
            "revenue_cents": 0,
            "coach_payroll_cents": None,
            "rent_cents": 0,
            "misc_expenses_cents": 0,
            "net_profit_cents": None,
            "profit_margin": None,
        },
        "payroll": {
            "estimated_cents": None,
            "approved_cents": None,
            "paid_cents": None,
            "unpaid_cents": None,
            "blocked_by": "No generated payout periods for this month.",
        },
        "empty_states": [
            "No collected payment rows found for this month.",
            "No attendance marks found for this month.",
            "No sessions found for this month.",
            "No expenses found for this month.",
            "No payout periods generated for this month.",
        ],
    }
