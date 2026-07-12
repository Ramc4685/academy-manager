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
            {"label": "Current", "amount_cents": 0, "family_count": 0, "families": []},
            {
                "label": "1-30",
                "amount_cents": 6_000,
                "family_count": 1,
                "families": [{"family_id": "parent-1", "family_name": None, "amount_cents": 6_000}],
            },
            {"label": "31-60", "amount_cents": 0, "family_count": 0, "families": []},
            {
                "label": "60+",
                "amount_cents": 3_000,
                "family_count": 1,
                "families": [{"family_id": "parent-2", "family_name": None, "amount_cents": 3_000}],
            },
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
        {"label": "Current", "amount_cents": 0, "family_count": 0, "families": []},
        {
            "label": "1-30",
            "amount_cents": 6_000,
            "family_count": 1,
            "families": [
                {"family_id": "parent-partial", "family_name": None, "amount_cents": 6_000}
            ],
        },
        {"label": "31-60", "amount_cents": 0, "family_count": 0, "families": []},
        {
            "label": "60+",
            "amount_cents": 3_000,
            "family_count": 1,
            "families": [
                {"family_id": "parent-failed", "family_name": None, "amount_cents": 3_000}
            ],
        },
    ]


@pytest.mark.asyncio
async def test_reports_dashboard_buckets_ledger_cash_by_paid_at_with_created_at_fallback() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]
    await db["ledger_payments"].insert_many(
        [
            {
                "payment_id": "paid-in-may-created-in-june",
                "academy_id": "acad",
                "parent_id": "parent-1",
                "amount_cents": 10_000,
                "currency": "usd",
                "status": "succeeded",
                "paid_at": datetime(2026, 5, 31, 23, 59, tzinfo=UTC),
                "created_at": datetime(2026, 6, 1, 0, 5, tzinfo=UTC),
            },
            {
                "payment_id": "paid-in-june-created-in-may",
                "academy_id": "acad",
                "parent_id": "parent-2",
                "amount_cents": 20_000,
                "currency": "usd",
                "status": "succeeded",
                "paid_at": datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
                "created_at": datetime(2026, 5, 31, 23, 58, tzinfo=UTC),
            },
            {
                "payment_id": "missing-paid-at",
                "academy_id": "acad",
                "parent_id": "parent-3",
                "amount_cents": 3_000,
                "currency": "usd",
                "status": "succeeded",
                "created_at": datetime(2026, 5, 15, tzinfo=UTC),
            },
            {
                "payment_id": "empty-paid-at",
                "academy_id": "acad",
                "parent_id": "parent-4",
                "amount_cents": 4_000,
                "currency": "usd",
                "status": "succeeded",
                "paid_at": "",
                "created_at": datetime(2026, 5, 16, tzinfo=UTC),
            },
            {
                "payment_id": "ledger-ignores-payment-date-and-period",
                "academy_id": "acad",
                "parent_id": "parent-5",
                "amount_cents": 7_000,
                "currency": "usd",
                "status": "succeeded",
                "payment_date": datetime(2026, 5, 15, tzinfo=UTC),
                "period": "2026-05",
                "created_at": datetime(2026, 6, 2, tzinfo=UTC),
            },
        ]
    )

    with tenant_scope("acad"):
        may_dashboard = await admin_composition._make_reports_dashboard(db)("2026-05")
        june_dashboard = await admin_composition._make_reports_dashboard(db)("2026-06")

    assert may_dashboard["cash_collected_cents"] == 17_000
    assert may_dashboard["profit_and_loss"]["revenue_cents"] == 17_000
    assert june_dashboard["cash_collected_cents"] == 27_000
    assert june_dashboard["profit_and_loss"]["revenue_cents"] == 27_000


@pytest.mark.asyncio
async def test_reports_dashboard_uses_legacy_effective_payment_date_before_period() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]
    await db["payments"].insert_many(
        [
            {
                "payment_id": "legacy-paid-at-may",
                "academy_id": "acad",
                "period": "2026-06",
                "status": "succeeded",
                "final_amount_cents": 1_000,
                "paid_at": datetime(2026, 5, 31, tzinfo=UTC),
                "payment_date": datetime(2026, 6, 1, tzinfo=UTC),
                "created_at": datetime(2026, 6, 2, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-payment-date-may",
                "academy_id": "acad",
                "period": "2026-06",
                "status": "succeeded",
                "final_amount_cents": 2_000,
                "payment_date": "2026-05-30",
                "created_at": datetime(2026, 6, 2, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-created-at-may",
                "academy_id": "acad",
                "period": "2026-06",
                "status": "succeeded",
                "final_amount_cents": 3_000,
                "created_at": datetime(2026, 5, 29, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-period-fallback-may",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 4_000,
            },
            {
                "payment_id": "legacy-paid-at-june-period-may",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 9_000,
                "paid_at": datetime(2026, 6, 1, tzinfo=UTC),
                "created_at": datetime(2026, 5, 31, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-partial-risk-may-cash-june",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "partially_paid",
                "parent_id": "parent-partial-may",
                "final_amount_cents": 10_000,
                "amount_received_cents": 5_000,
                "balance_due_cents": 5_000,
                "paid_at": datetime(2026, 6, 2, tzinfo=UTC),
                "created_at": datetime(2026, 5, 31, tzinfo=UTC),
                "due_date": "2026-05-15",
            },
            {
                "payment_id": "legacy-failed-risk-may-created-june",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "failed",
                "parent_id": "parent-failed-may",
                "final_amount_cents": 3_000,
                "created_at": datetime(2026, 6, 3, tzinfo=UTC),
                "due_date": "2026-04-01",
            },
            {
                "payment_id": "legacy-partial-risk-june-cash-may",
                "academy_id": "acad",
                "period": "2026-06",
                "status": "partially_paid",
                "parent_id": "parent-partial-june",
                "final_amount_cents": 10_000,
                "amount_received_cents": 6_000,
                "balance_due_cents": 4_000,
                "payment_date": "2026-05-30",
                "created_at": datetime(2026, 6, 4, tzinfo=UTC),
                "due_date": "2026-06-15",
            },
            {
                "payment_id": "legacy-ledger-duplicate-without-invoice-key",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 8_000,
                "stripe_payment_intent_id": "pi_ledger_duplicate",
                "paid_at": datetime(2026, 5, 30, tzinfo=UTC),
                "created_at": datetime(2026, 5, 30, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-cross-period-ledger-duplicate",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 7_000,
                "stripe_payment_intent_id": "pi_cross_period_duplicate",
                "paid_at": datetime(2026, 5, 29, tzinfo=UTC),
                "created_at": datetime(2026, 5, 29, tzinfo=UTC),
            },
            {
                "payment_id": "legacy-allocation-duplicate",
                "academy_id": "acad",
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 5_000,
                "invoice_id": "inv_allocation_duplicate",
                "paid_at": datetime(2026, 5, 30, tzinfo=UTC),
                "created_at": datetime(2026, 5, 30, tzinfo=UTC),
            },
        ]
    )
    await db["ledger_payments"].insert_many(
        [
            {
                "payment_id": "ledger-duplicate-without-invoice-key",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 8_000,
                "stripe_payment_intent_id": "pi_ledger_duplicate",
                "paid_at": datetime(2026, 5, 30, tzinfo=UTC),
                "created_at": datetime(2026, 5, 30, tzinfo=UTC),
            },
            {
                "payment_id": "ledger-cross-period-duplicate",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 7_000,
                "stripe_payment_intent_id": "pi_cross_period_duplicate",
                "paid_at": datetime(2026, 6, 3, tzinfo=UTC),
                "created_at": datetime(2026, 6, 3, tzinfo=UTC),
            },
            {
                "payment_id": "ledger-allocation-duplicate",
                "academy_id": "acad",
                "status": "succeeded",
                "amount_cents": 5_000,
                "paid_at": datetime(2026, 5, 30, tzinfo=UTC),
                "created_at": datetime(2026, 5, 30, tzinfo=UTC),
            },
        ]
    )
    await db["payment_allocations"].insert_one(
        {
            "academy_id": "acad",
            "payment_id": "ledger-allocation-duplicate",
            "invoice_id": "inv_allocation_duplicate",
        }
    )

    with tenant_scope("acad"):
        may_dashboard = await admin_composition._make_reports_dashboard(db)("2026-05")
        june_dashboard = await admin_composition._make_reports_dashboard(db)("2026-06")

    assert may_dashboard["cash_collected_cents"] == 29_000
    assert may_dashboard["collections_risk"]["failed_payment_count"] == 1
    assert may_dashboard["collections_risk"]["partial_payment_count"] == 1
    assert may_dashboard["collections_risk"]["overdue_family_count"] == 2
    assert may_dashboard["collections_risk"]["overdue_cents"] == 8_000
    assert may_dashboard["collections_risk"]["aging_buckets"] == [
        {"label": "Current", "amount_cents": 0, "family_count": 0, "families": []},
        {
            "label": "1-30",
            "amount_cents": 5_000,
            "family_count": 1,
            "families": [
                {
                    "family_id": "parent-partial-may",
                    "family_name": None,
                    "amount_cents": 5_000,
                }
            ],
        },
        {"label": "31-60", "amount_cents": 0, "family_count": 0, "families": []},
        {
            "label": "60+",
            "amount_cents": 3_000,
            "family_count": 1,
            "families": [
                {
                    "family_id": "parent-failed-may",
                    "family_name": None,
                    "amount_cents": 3_000,
                }
            ],
        },
    ]
    assert june_dashboard["cash_collected_cents"] == 21_000
    assert june_dashboard["collections_risk"]["failed_payment_count"] == 0
    assert june_dashboard["collections_risk"]["partial_payment_count"] == 1
    assert june_dashboard["collections_risk"]["overdue_family_count"] == 1
    assert june_dashboard["collections_risk"]["overdue_cents"] == 4_000


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
        "billed_cents": 0,
        "collection_rate": None,
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
                {"label": "Current", "amount_cents": 0, "family_count": 0, "families": []},
                {"label": "1-30", "amount_cents": 0, "family_count": 0, "families": []},
                {"label": "31-60", "amount_cents": 0, "family_count": 0, "families": []},
                {"label": "60+", "amount_cents": 0, "family_count": 0, "families": []},
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


@pytest.mark.asyncio
async def test_session_economics_prorates_monthly_fee_and_allocates_costs() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]

    await db["sessions"].insert_one(
        {
            "session_id": "sess-beginner",
            "academy_id": "acad",
            "title": "Wednesday 5:45 PM Beginner",
            "coach_name": "Kishore",
            "amount_cents": 60_000,
            "capacity": 8,
            "status": "scheduled",
            "start_at": datetime(2026, 4, 1, 22, 45, tzinfo=UTC),
        }
    )
    await db["session_occurrences"].insert_many(
        [
            {
                "occurrence_id": f"occ-{day}",
                "academy_id": "acad",
                "session_id": "sess-beginner",
                "template_session_id": "sess-beginner",
                "status": "scheduled",
                "start_at": datetime(2026, 4, day, 22, 45, tzinfo=UTC),
                "end_at": datetime(2026, 4, day, 23, 30, tzinfo=UTC),
            }
            for day in (1, 8, 15, 22)
        ]
    )
    await db["enrollments"].insert_one(
        {
            "enrollment_id": "enr-beginner",
            "academy_id": "acad",
            "session_id": "sess-beginner",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "status": "active",
        }
    )
    await db["invoices"].insert_one(
        {
            "invoice_id": "inv-beginner",
            "academy_id": "acad",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enr-beginner",
            "period": "2026-04",
            "status": "paid",
            "subtotal_cents": 60_000,
            "discount_cents": 0,
            "total_cents": 60_000,
            "balance_due_cents": 0,
            "currency": "usd",
            "created_at": datetime(2026, 4, 2, tzinfo=UTC),
            "updated_at": datetime(2026, 4, 2, tzinfo=UTC),
        }
    )
    await db["expenses"].insert_many(
        [
            {
                "expense_id": "exp-rent",
                "academy_id": "acad",
                "category": "rent",
                "amount_cents": 10_000,
                "incurred_on": datetime(2026, 4, 2, tzinfo=UTC),
            },
            {
                "expense_id": "exp-other",
                "academy_id": "acad",
                "category": "equipment",
                "amount_cents": 5_000,
                "incurred_on": datetime(2026, 4, 3, tzinfo=UTC),
            },
        ]
    )
    await db["payout_periods"].insert_one(
        {
            "period_id": "pp-kishore",
            "academy_id": "acad",
            "coach_id": "coach-kishore",
            "period_start": datetime(2026, 4, 1, tzinfo=UTC),
            "period_end": datetime(2026, 5, 1, tzinfo=UTC),
            "status": "draft",
            "currency": "USD",
            "total_minor": 18_000,
        }
    )
    await db["payout_period_lines"].insert_many(
        [
            {
                "period_id": "pp-kishore",
                "academy_id": "acad",
                "occurrence_id": f"occ-{day}",
                "coach_id": "coach-kishore",
                "amount_minor": 4_500,
                "expected_revenue_minor": 15_000,
                "percent_bps": 3000,
            }
            for day in (1, 8, 15, 22)
        ]
    )

    with tenant_scope("acad"):
        report = await admin_composition._make_session_economics_report(db)("2026-04")

    assert report["summary"] == {
        "expected_revenue_cents": 60_000,
        "paid_cents": 60_000,
        "unpaid_cents": 0,
        "coach_payroll_cents": 18_000,
        "rent_cents": 10_000,
        "other_expenses_cents": 5_000,
        "expected_profit_cents": 27_000,
        "profit_margin": 0.45,
    }
    assert report["sessions"] == [
        {
            "session_id": "sess-beginner",
            "title": "Wednesday 5:45 PM Beginner",
            "coach_name": "Kishore",
            "active_enrollment_count": 1,
            "paid_student_count": 1,
            "unpaid_student_count": 0,
            "monthly_fee_cents": 60_000,
            "payable_occurrence_count": 4,
            "expected_revenue_per_occurrence_cents": 15_000,
            "expected_revenue_cents": 60_000,
            "paid_cents": 60_000,
            "unpaid_cents": 0,
            "coach_payroll_cents": 18_000,
            "rent_cents": 10_000,
            "other_expenses_cents": 5_000,
            "expected_profit_cents": 27_000,
            "profit_margin": 0.45,
        }
    ]
    assert report["empty_states"] == []


@pytest.mark.asyncio
async def test_reports_dashboard_reports_billed_collection_rate_and_family_names() -> None:
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
                "invoice_id": "inv-open",
                "academy_id": "acad",
                "parent_id": "parent-open",
                "period": "2026-05",
                "status": "open",
                "total_cents": 5_000,
                "balance_due_cents": 5_000,
                "currency": "usd",
                "created_at": datetime(2026, 5, 5, tzinfo=UTC),
                "due_date": datetime(2026, 5, 20, tzinfo=UTC),
            },
        ]
    )
    await db["ledger_payments"].insert_one(
        {
            "payment_id": "lp-paid",
            "academy_id": "acad",
            "parent_id": "parent-paid",
            "amount_cents": 10_000,
            "currency": "usd",
            "status": "succeeded",
            "created_at": datetime(2026, 5, 4, tzinfo=UTC),
        }
    )
    await db["users"].insert_many(
        [
            {
                "user_id": "parent-open",
                "academy_id": "acad",
                "display_name": "Open Family",
            },
            {
                # Same user_id under another tenant must never win the lookup.
                "user_id": "parent-open",
                "academy_id": "other",
                "display_name": "Wrong Tenant Family",
            },
        ]
    )

    with tenant_scope("acad"):
        dashboard = await admin_composition._make_reports_dashboard(db)("2026-05")

    assert dashboard["billed_cents"] == 15_000
    assert dashboard["cash_collected_cents"] == 10_000
    assert dashboard["collection_rate"] == 0.6667
    one_to_thirty = dashboard["collections_risk"]["aging_buckets"][1]
    assert one_to_thirty["label"] == "1-30"
    assert one_to_thirty["families"] == [
        {"family_id": "parent-open", "family_name": "Open Family", "amount_cents": 5_000}
    ]


@pytest.mark.asyncio
async def test_projected_income_splits_autopay_vs_manual_with_overrides() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]
    await db["sessions"].insert_many(
        [
            {
                "session_id": "sess-a",
                "academy_id": "acad",
                "title": "Monday Advanced",
                "amount_cents": 20_000,
            },
            {
                "session_id": "sess-b",
                "academy_id": "acad",
                "title": "Friday Beginner",
                "amount_cents": 15_000,
            },
            {
                "session_id": "sess-free",
                "academy_id": "acad",
                "title": "Free Clinic",
                "amount_cents": 0,
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "enrollment_id": "enr-1",
                "academy_id": "acad",
                "session_id": "sess-a",
                "status": "active",
            },
            {
                "enrollment_id": "enr-2",
                "academy_id": "acad",
                "session_id": "sess-a",
                "status": "active",
            },
            {
                "enrollment_id": "enr-3",
                "academy_id": "acad",
                "session_id": "sess-b",
                "status": "active",
            },
            {
                "enrollment_id": "enr-free",
                "academy_id": "acad",
                "session_id": "sess-free",
                "status": "active",
            },
            {
                "enrollment_id": "enr-paused",
                "academy_id": "acad",
                "session_id": "sess-a",
                "status": "paused",
            },
            {
                "enrollment_id": "enr-other-tenant",
                "academy_id": "other",
                "session_id": "sess-a",
                "status": "active",
            },
        ]
    )
    await db["student_billing_enrollments"].insert_many(
        [
            {
                "enrollment_id": "enr-1",
                "academy_id": "acad",
                "autopay_enrollment_status": "active",
            },
            {
                "enrollment_id": "enr-2",
                "academy_id": "acad",
                "autopay_enrollment_status": "paused",
            },
            {
                "enrollment_id": "enr-3",
                "academy_id": "acad",
                "autopay_enrollment_status": "active",
                "override_price_cents": 12_000,
            },
        ]
    )

    with tenant_scope("acad"):
        projection = await admin_composition._make_projected_income_report(db)("2026-08")

    assert projection["period"] == "2026-08"
    assert projection["total_cents"] == 52_000
    assert projection["autopay_cents"] == 32_000
    assert projection["manual_cents"] == 20_000
    assert projection["enrollment_count"] == 3
    assert projection["autopay_enrollment_count"] == 2
    assert projection["manual_enrollment_count"] == 1
    assert projection["by_session"] == [
        {
            "session_id": "sess-a",
            "title": "Monday Advanced",
            "monthly_fee_cents": 20_000,
            "enrollment_count": 2,
            "expected_cents": 40_000,
        },
        {
            "session_id": "sess-b",
            "title": "Friday Beginner",
            "monthly_fee_cents": 15_000,
            "enrollment_count": 1,
            "expected_cents": 12_000,
        },
    ]
    assert projection["empty"] is False


@pytest.mark.asyncio
async def test_projected_income_empty_when_no_active_enrollments() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_db"]

    with tenant_scope("acad"):
        projection = await admin_composition._make_projected_income_report(db)("2026-08")

    assert projection["total_cents"] == 0
    assert projection["by_session"] == []
    assert projection["empty"] is True
