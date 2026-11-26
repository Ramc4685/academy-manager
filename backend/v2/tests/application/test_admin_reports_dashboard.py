"""Admin reports dashboard composition tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import backend.v2.contexts.billing.infrastructure.admin_reports_read_model as reports_read_model
from backend.v2.composition.admin_session_staff import attach_session_staff_names
from backend.v2.shared.tenancy.context import tenant_scope


def _economics_report(db):
    """Session economics wired with the admin sessions staff-name resolver,
    the way ``composition/admin.py`` wires it."""
    return reports_read_model.make_session_economics_report(
        db, staff_names=lambda rows: attach_session_staff_names(db, rows)
    )


async def _seed_members(db, *user_ids: str, academy_id: str = "acad") -> None:
    await db["academy_memberships"].insert_many(
        [
            {"academy_id": academy_id, "user_id": uid, "roles": ["coach"], "status": "active"}
            for uid in user_ids
        ]
    )


@pytest.fixture(autouse=True)
def _aging_clock(monkeypatch):
    """Aging is "how late now". Most fixtures here are May 2026 balances viewed
    on June 1, so pin the clock there; aging tests below set their own."""
    monkeypatch.setattr(reports_read_model, "_now", lambda: datetime(2026, 6, 1, 12, tzinfo=UTC))


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
                "occurrence_id": "occ-2",
                "status": "present",
                "marked_at": datetime(2026, 5, 3, tzinfo=UTC),
            },
            {
                "attendance_id": "att-2",
                "academy_id": "acad",
                "occurrence_id": "occ-2",
                "status": "late",
                "marked_at": datetime(2026, 5, 4, tzinfo=UTC),
            },
            {
                "attendance_id": "att-3",
                "academy_id": "acad",
                "occurrence_id": "occ-2",
                "status": "absent",
                "marked_at": datetime(2026, 5, 5, tzinfo=UTC),
            },
            {
                "attendance_id": "att-other",
                "academy_id": "other",
                "occurrence_id": "occ-2",
                "status": "present",
                "marked_at": datetime(2026, 5, 6, tzinfo=UTC),
            },
        ]
    )
    # One class date of each kind: upcoming, held (by the clock) and cancelled.
    await db["session_occurrences"].insert_many(
        [
            {
                "occurrence_id": "occ-1",
                "academy_id": "acad",
                "session_id": "sess-1",
                "status": "scheduled",
                "start_at": datetime(2026, 5, 30, tzinfo=UTC),
                "end_at": datetime(2999, 5, 30, tzinfo=UTC),
            },
            {
                "occurrence_id": "occ-2",
                "academy_id": "acad",
                "session_id": "sess-2",
                "status": "scheduled",
                "start_at": datetime(2026, 5, 2, 14, tzinfo=UTC),
                "end_at": datetime(2026, 5, 2, 15, tzinfo=UTC),
            },
            {
                "occurrence_id": "occ-3",
                "academy_id": "acad",
                "session_id": "sess-3",
                "status": "cancelled",
                "start_at": datetime(2026, 5, 9, tzinfo=UTC),
                "end_at": datetime(2026, 5, 9, 1, tzinfo=UTC),
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
        dashboard = await reports_read_model.make_reports_dashboard(db)("2026-05")

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
        "paying_seats": 2,
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
    # One of the three payout periods is still draft, so P&L must not present a
    # profit number off payroll that is not finalised (#225).
    assert dashboard["profit_and_loss"] == {
        "revenue_cents": 13_000,
        "coach_payroll_cents": None,
        "rent_cents": 5_000,
        "misc_expenses_cents": 1_200,
        "net_profit_cents": None,
        "profit_margin": None,
    }
    # Estimated/approved/paid stay visible so the month is still previewable.
    assert dashboard["payroll"] == {
        "estimated_cents": 13_000,
        "approved_cents": 9_000,
        "paid_cents": 3_000,
        "unpaid_cents": 6_000,
        "blocked_by": "1 payout period is still in draft.",
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
        dashboard = await reports_read_model.make_reports_dashboard(db)("2026-05")

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
        may_dashboard = await reports_read_model.make_reports_dashboard(db)("2026-05")
        june_dashboard = await reports_read_model.make_reports_dashboard(db)("2026-06")

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
        may_dashboard = await reports_read_model.make_reports_dashboard(db)("2026-05")
        june_dashboard = await reports_read_model.make_reports_dashboard(db)("2026-06")

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
        dashboard = await reports_read_model.make_reports_dashboard(db)("2026-05")

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
            "paying_seats": 0,
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
        # No coach occurrences means no payroll is owed, so P&L is accurate at
        # zero rather than blocked on missing payout periods (#225).
        "profit_and_loss": {
            "revenue_cents": 0,
            "coach_payroll_cents": 0,
            "rent_cents": 0,
            "misc_expenses_cents": 0,
            "net_profit_cents": 0,
            "profit_margin": None,
        },
        "payroll": {
            "estimated_cents": None,
            "approved_cents": None,
            "paid_cents": None,
            "unpaid_cents": None,
            "blocked_by": None,
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
            "coach_id": "coach-kishore",
            "assistant_coach_ids": ["coach-casey"],
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
            "status": "approved",
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

    await db["users"].insert_many(
        [
            {"user_id": "coach-kishore", "display_name": "Kishore"},
            {"user_id": "coach-casey", "display_name": "Casey Newcoach"},
        ]
    )
    await _seed_members(db, "coach-kishore", "coach-casey")

    with tenant_scope("acad"):
        report = await _economics_report(db)("2026-04")

    assert report["summary"] == {
        "expected_revenue_cents": 60_000,
        "paid_cents": 60_000,
        "unpaid_cents": 0,
        "coach_payroll_cents": 18_000,
        "rent_cents": 10_000,
        "other_expenses_cents": 5_000,
        "payroll_status": "complete",
        "payroll_blocked_by": None,
        "expected_profit_cents": 27_000,
        "profit_margin": 0.45,
    }
    assert report["sessions"] == [
        {
            "session_id": "sess-beginner",
            "title": "Wednesday 5:45 PM Beginner",
            "coach_name": "Kishore, Casey Newcoach",
            "active_enrollment_count": 1,
            "not_billed_enrollment_count": 0,
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
            "payroll_status": "complete",
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
        dashboard = await reports_read_model.make_reports_dashboard(db)("2026-05")

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
                "enrollment_id": "enr-scholarship",
                "academy_id": "acad",
                "session_id": "sess-a",
                "status": "active",
                "billing_type": "NoCharge",
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
        projection = await reports_read_model.make_projected_income_report(db)("2026-08")

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
            "enrolled_count": 3,
            "expected_cents": 40_000,
        },
        {
            "session_id": "sess-b",
            "title": "Friday Beginner",
            "monthly_fee_cents": 15_000,
            "enrollment_count": 1,
            "enrolled_count": 1,
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
        projection = await reports_read_model.make_projected_income_report(db)("2026-08")

    assert projection["total_cents"] == 0
    assert projection["by_session"] == []
    assert projection["empty"] is True


# ---------------------------------------------------------------------------
# P&L payroll completeness (#225)
#
# The dashboard must never present a confident net profit off payroll that is
# missing, still draft, or generated with gaps. Blocked P&L is signalled the
# way the zero-payroll case already is: null payroll/profit/margin plus a
# ``payroll.blocked_by`` reason.
# ---------------------------------------------------------------------------

_MAY = datetime(2026, 5, 1, tzinfo=UTC)
_JUNE = datetime(2026, 6, 1, tzinfo=UTC)


def _payroll_db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["test_db"]


async def _seed_cash(db, *, academy_id: str = "acad", amount_cents: int = 20_000) -> None:
    await db["ledger_payments"].insert_one(
        {
            "payment_id": f"lp-{academy_id}",
            "academy_id": academy_id,
            "parent_id": "parent-1",
            "amount_cents": amount_cents,
            "currency": "usd",
            "status": "succeeded",
            "paid_at": datetime(2026, 5, 10, tzinfo=UTC),
        }
    )


async def _seed_past_occurrence(
    db,
    occurrence_id: str,
    *,
    academy_id: str = "acad",
    scheduled_coach_id: str = "coach-1",
    actual_coach_id: str | None = None,
    status: str = "completed",
    is_payable: bool = True,
) -> None:
    await db["session_occurrences"].insert_one(
        {
            "academy_id": academy_id,
            "occurrence_id": occurrence_id,
            "session_id": "sess-1",
            "start_at": datetime(2026, 5, 10, 18, tzinfo=UTC),
            "end_at": datetime(2026, 5, 10, 19, tzinfo=UTC),
            "status": status,
            "scheduled_coach_id": scheduled_coach_id,
            "actual_coach_id": actual_coach_id,
            "is_payable": is_payable,
        }
    )


async def _seed_period(
    db,
    period_id: str,
    *,
    coach_id: str,
    status: str,
    total_minor: int,
    academy_id: str = "acad",
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    **extra,
) -> None:
    doc = {
        "period_id": period_id,
        "academy_id": academy_id,
        "coach_id": coach_id,
        "period_start": period_start or _MAY,
        "period_end": period_end or _JUNE,
        "status": status,
        "total_minor": total_minor,
    }
    if status == "paid":
        doc.setdefault("paid_amount_minor", total_minor)
    doc.update(extra)
    await db["payout_periods"].insert_one(doc)


async def _dashboard(db, academy_id: str = "acad") -> dict:
    with tenant_scope(academy_id):
        return await reports_read_model.make_reports_dashboard(db)("2026-05")


@pytest.mark.asyncio
async def test_pnl_blocked_when_a_coach_has_no_payout_period() -> None:
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_past_occurrence(db, "occ-2", scheduled_coach_id="coach-2")
    await _seed_period(db, "pp-1", coach_id="coach-1", status="approved", total_minor=5_000)

    dashboard = await _dashboard(db)

    assert dashboard["profit_and_loss"]["coach_payroll_cents"] is None
    assert dashboard["profit_and_loss"]["net_profit_cents"] is None
    assert dashboard["profit_and_loss"]["profit_margin"] is None
    assert dashboard["payroll"]["blocked_by"] is not None
    assert "1 coach" in dashboard["payroll"]["blocked_by"]
    # The estimate stays visible so owners can still preview the month.
    assert dashboard["payroll"]["estimated_cents"] == 5_000


@pytest.mark.asyncio
async def test_pnl_blocked_while_any_payout_period_is_still_draft() -> None:
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_past_occurrence(db, "occ-2", scheduled_coach_id="coach-2")
    await _seed_period(db, "pp-1", coach_id="coach-1", status="approved", total_minor=5_000)
    await _seed_period(db, "pp-2", coach_id="coach-2", status="draft", total_minor=4_000)

    dashboard = await _dashboard(db)

    assert dashboard["profit_and_loss"]["net_profit_cents"] is None
    assert "draft" in dashboard["payroll"]["blocked_by"]
    assert dashboard["payroll"]["estimated_cents"] == 9_000
    assert dashboard["payroll"]["approved_cents"] == 5_000


@pytest.mark.asyncio
async def test_pnl_blocked_when_a_payout_period_has_unresolved_unpaid_occurrences() -> None:
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_period(
        db,
        "pp-1",
        coach_id="coach-1",
        status="approved",
        total_minor=5_000,
        unpaid_occurrence_ids=["occ-no-rate"],
    )

    dashboard = await _dashboard(db)

    assert dashboard["profit_and_loss"]["net_profit_cents"] is None
    assert "unresolved" in dashboard["payroll"]["blocked_by"]


@pytest.mark.asyncio
async def test_pnl_blocked_when_a_payout_period_does_not_cover_the_whole_month() -> None:
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_period(
        db,
        "pp-1",
        coach_id="coach-1",
        status="approved",
        total_minor=5_000,
        period_end=datetime(2026, 5, 16, tzinfo=UTC),
    )

    dashboard = await _dashboard(db)

    assert dashboard["profit_and_loss"]["net_profit_cents"] is None
    assert "full month" in dashboard["payroll"]["blocked_by"]


@pytest.mark.asyncio
async def test_pnl_uses_finalised_payroll_when_the_month_is_complete() -> None:
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_past_occurrence(
        db, "occ-2", scheduled_coach_id="coach-2", actual_coach_id="coach-3"
    )
    await _seed_period(db, "pp-1", coach_id="coach-1", status="approved", total_minor=5_000)
    await _seed_period(db, "pp-3", coach_id="coach-3", status="paid", total_minor=4_000)

    dashboard = await _dashboard(db)

    assert dashboard["payroll"]["blocked_by"] is None
    # Obligation (total_minor), not cash paid.
    assert dashboard["profit_and_loss"]["coach_payroll_cents"] == 9_000
    assert dashboard["profit_and_loss"]["net_profit_cents"] == 11_000
    assert dashboard["payroll"]["paid_cents"] == 4_000
    assert dashboard["payroll"]["unpaid_cents"] == 5_000


@pytest.mark.asyncio
async def test_pnl_not_blocked_when_the_month_has_no_payable_coach_occurrences() -> None:
    """A month with no coach work owes no payroll, so P&L is accurate at zero."""
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-cancelled", status="cancelled")
    await _seed_past_occurrence(db, "occ-unpayable", is_payable=False)

    dashboard = await _dashboard(db)

    assert dashboard["payroll"]["blocked_by"] is None
    assert dashboard["profit_and_loss"]["coach_payroll_cents"] == 0
    assert dashboard["profit_and_loss"]["net_profit_cents"] == 20_000


@pytest.mark.asyncio
async def test_payroll_completeness_is_scoped_to_the_requesting_tenant() -> None:
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_period(db, "pp-1", coach_id="coach-1", status="approved", total_minor=5_000)
    # Another academy's ungenerated payroll must not block this one.
    await _seed_past_occurrence(
        db, "occ-other", academy_id="other-acad", scheduled_coach_id="coach-x"
    )

    dashboard = await _dashboard(db)

    assert dashboard["payroll"]["blocked_by"] is None
    assert dashboard["profit_and_loss"]["coach_payroll_cents"] == 5_000


@pytest.mark.asyncio
async def test_payroll_window_match_tolerates_naive_datetimes_from_mongo() -> None:
    """The app's Motor client is not ``tz_aware``, so it returns naive UTC.

    ``month_bounds`` is timezone-aware. Comparing the two directly would mark
    every real payout period as not covering the month and block P&L forever.
    """
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_period(
        db,
        "pp-1",
        coach_id="coach-1",
        status="approved",
        total_minor=5_000,
        period_start=datetime(2026, 5, 1),
        period_end=datetime(2026, 6, 1),
    )

    dashboard = await _dashboard(db)

    assert dashboard["payroll"]["blocked_by"] is None
    assert dashboard["profit_and_loss"]["coach_payroll_cents"] == 5_000


@pytest.mark.asyncio
async def test_payroll_completeness_ignores_non_blocking_unpaid_rows() -> None:
    """A replaced or absent coach explains a zero; it is not missing payroll."""
    db = _payroll_db()
    await _seed_cash(db)
    await _seed_past_occurrence(db, "occ-1", scheduled_coach_id="coach-1")
    await _seed_period(
        db,
        "pp-1",
        coach_id="coach-1",
        status="approved",
        total_minor=5_000,
        unpaid_occurrences=[
            {
                "occurrence_id": "occ-replaced",
                "reason": "replaced_by_actual_coach",
                "detail": "Scheduled coach was replaced.",
                "unresolved": False,
                "attributed_coach_id": "coach-2",
            }
        ],
    )

    dashboard = await _dashboard(db)

    assert dashboard["payroll"]["blocked_by"] is None
    assert dashboard["profit_and_loss"]["coach_payroll_cents"] == 5_000


def _aging(dashboard: dict) -> dict[str, int]:
    return {b["label"]: b["amount_cents"] for b in dashboard["collections_risk"]["aging_buckets"]}


@pytest.mark.asyncio
async def test_aging_ages_against_today_not_the_month_end(monkeypatch) -> None:
    """G:ai_owner:1: a not-yet-due invoice read 1-30 during its own month, and a
    balance viewed months later never left 1-30."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["test_db"]
    await db["invoices"].insert_many(
        [
            {
                "invoice_id": "inv-not-due",
                "academy_id": "acad",
                "parent_id": "parent-a",
                "period": "2026-11",
                "status": "open",
                "total_cents": 4_000,
                "balance_due_cents": 4_000,
                "currency": "usd",
                "created_at": datetime(2026, 11, 1, tzinfo=UTC),
                "due_date": datetime(2026, 11, 20, tzinfo=UTC),
            },
            {
                "invoice_id": "inv-sept",
                "academy_id": "acad",
                "parent_id": "parent-b",
                "period": "2026-09",
                "status": "open",
                "total_cents": 7_000,
                "balance_due_cents": 7_000,
                "currency": "usd",
                "created_at": datetime(2026, 9, 1, tzinfo=UTC),
                "due_date": datetime(2026, 9, 5, tzinfo=UTC),
            },
        ]
    )
    monkeypatch.setattr(reports_read_model, "_now", lambda: datetime(2026, 11, 15, 18, tzinfo=UTC))

    with tenant_scope("acad"):
        november = await reports_read_model.make_reports_dashboard(db)("2026-11")
        september = await reports_read_model.make_reports_dashboard(db)("2026-09")

    assert _aging(november) == {"Current": 4_000, "1-30": 0, "31-60": 0, "60+": 0}
    # Due Sep 5, unpaid on Nov 15: 71 days late.
    assert _aging(september) == {"Current": 0, "1-30": 0, "31-60": 0, "60+": 7_000}


@pytest.mark.asyncio
async def test_month_counts_classes_that_meet_in_it_not_only_ones_that_began() -> None:
    """G:ai_owner:2: a class that began in September vanished from November."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["test_db"]
    await db["sessions"].insert_many(
        [
            {
                "academy_id": "acad",
                "session_id": "ses-sept",
                "start_at": datetime(2026, 9, 7, 23, tzinfo=UTC),
                "capacity": 10,
                "status": "scheduled",
            },
            {
                # Ended in October: no November occurrence, not counted.
                "academy_id": "acad",
                "session_id": "ses-ended",
                "start_at": datetime(2026, 8, 3, 23, tzinfo=UTC),
                "capacity": 8,
                "status": "scheduled",
            },
        ]
    )
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": "acad",
                "occurrence_id": "occ-nov",
                "session_id": "ses-sept",
                "start_at": datetime(2026, 11, 9, 23, tzinfo=UTC),
            },
            {
                "academy_id": "acad",
                "occurrence_id": "occ-oct",
                "session_id": "ses-ended",
                "start_at": datetime(2026, 10, 5, 23, tzinfo=UTC),
            },
            {
                # Another academy's occurrence naming the same class id.
                "academy_id": "other",
                "occurrence_id": "occ-other",
                "session_id": "ses-ended",
                "start_at": datetime(2026, 11, 9, 23, tzinfo=UTC),
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": "acad",
                "session_id": "ses-sept",
                "student_id": f"s{i}",
                "status": "active",
            }
            for i in range(4)
        ]
    )
    await db["waitlist"].insert_one(
        {"academy_id": "acad", "session_id": "ses-sept", "status": "waiting"}
    )

    with tenant_scope("acad"):
        dashboard = await reports_read_model.make_reports_dashboard(db)("2026-11")

    assert dashboard["sessions"]["scheduled_count"] == 1
    assert dashboard["sessions"]["capacity_utilization"] == 0.4
    assert dashboard["sessions"]["waitlist_count"] == 1


async def _seed_economics_class(db, *, end_at: datetime) -> None:
    await db["sessions"].insert_one(
        {
            "session_id": "sess-1",
            "academy_id": "acad",
            "title": "Junior Beginners",
            "coach_id": "coach-1",
            "amount_cents": 8_000,
        }
    )
    await db["session_occurrences"].insert_one(
        {
            "occurrence_id": "occ-1",
            "academy_id": "acad",
            "session_id": "sess-1",
            "status": "scheduled",
            "scheduled_coach_id": "coach-1",
            "start_at": datetime(2026, 5, 9, 14, tzinfo=UTC),
            "end_at": end_at,
        }
    )
    await db["enrollments"].insert_one(
        {
            "enrollment_id": "enr-1",
            "academy_id": "acad",
            "session_id": "sess-1",
            "status": "active",
        }
    )
    await db["users"].insert_one({"user_id": "coach-1", "display_name": "Demo Coach"})
    await _seed_members(db, "coach-1")


async def _economics(db) -> dict:
    with tenant_scope("acad"):
        return await _economics_report(db)("2026-05")


@pytest.mark.asyncio
async def test_session_economics_never_names_a_coach_from_another_academy() -> None:
    db = _payroll_db()
    await _seed_economics_class(db, end_at=datetime(2026, 5, 9, 15, tzinfo=UTC))
    await db["sessions"].update_one({"session_id": "sess-1"}, {"$set": {"coach_id": "outsider"}})
    await db["users"].insert_one({"user_id": "outsider", "display_name": "Other Academy Person"})
    await _seed_members(db, "outsider", academy_id="other")

    report = await _economics(db)

    assert report["sessions"][0]["coach_name"] is None


@pytest.mark.asyncio
async def test_session_economics_names_a_coach_keyed_by_mongo_id() -> None:
    from bson import ObjectId

    db = _payroll_db()
    await _seed_economics_class(db, end_at=datetime(2026, 5, 9, 15, tzinfo=UTC))
    oid = ObjectId()
    await db["users"].insert_one(
        {"_id": oid, "user_id": "coach-oid", "display_name": "Object Id Coach"}
    )
    await db["sessions"].update_one({"session_id": "sess-1"}, {"$set": {"coach_id": str(oid)}})
    await _seed_members(db, "coach-oid")

    report = await _economics(db)

    assert report["sessions"][0]["coach_name"] == "Object Id Coach"


@pytest.mark.asyncio
async def test_session_economics_withholds_margin_until_payroll_is_generated() -> None:
    db = _payroll_db()
    await _seed_economics_class(db, end_at=datetime(2026, 5, 9, 15, tzinfo=UTC))

    report = await _economics(db)

    row = report["sessions"][0]
    assert row["coach_name"] == "Demo Coach"
    assert row["payroll_status"] == "needs_payroll"
    assert row["expected_profit_cents"] is None
    assert row["profit_margin"] is None
    assert report["summary"]["payroll_status"] == "needs_payroll"
    assert report["summary"]["expected_profit_cents"] is None
    assert report["summary"]["profit_margin"] is None
    assert report["summary"]["payroll_blocked_by"] == "No generated payout periods for this month."


@pytest.mark.asyncio
async def test_session_economics_withholds_margin_while_payroll_is_draft() -> None:
    db = _payroll_db()
    await _seed_economics_class(db, end_at=datetime(2026, 5, 9, 15, tzinfo=UTC))
    await _seed_period(db, "pp-1", coach_id="coach-1", status="draft", total_minor=3_000)

    report = await _economics(db)

    assert report["sessions"][0]["payroll_status"] == "needs_payroll"
    assert report["summary"]["profit_margin"] is None


@pytest.mark.asyncio
async def test_session_economics_shows_margin_once_payroll_is_approved() -> None:
    db = _payroll_db()
    await _seed_economics_class(db, end_at=datetime(2026, 5, 9, 15, tzinfo=UTC))
    await _seed_period(db, "pp-1", coach_id="coach-1", status="approved", total_minor=3_000)
    await db["payout_period_lines"].insert_one(
        {"period_id": "pp-1", "academy_id": "acad", "occurrence_id": "occ-1", "amount_minor": 3_000}
    )

    report = await _economics(db)

    row = report["sessions"][0]
    assert row["payroll_status"] == "complete"
    assert row["expected_profit_cents"] == 5_000
    assert row["profit_margin"] == 0.625
    assert report["summary"]["payroll_status"] == "complete"
    assert report["summary"]["profit_margin"] == 0.625


@pytest.mark.asyncio
async def test_session_economics_withholds_margin_for_classes_not_yet_held() -> None:
    db = _payroll_db()
    # Ends in the future: nothing to pay yet, so no final margin.
    await _seed_economics_class(db, end_at=datetime(2999, 5, 9, 15, tzinfo=UTC))

    report = await _economics(db)

    assert report["sessions"][0]["payroll_status"] == "needs_payroll"
    assert report["summary"]["payroll_blocked_by"] == (
        "Some classes this month have not been held yet."
    )


@pytest.mark.asyncio
async def test_completed_equals_held_class_dates_and_attendance_reads_by_class_date() -> None:
    """Bug-06: 82% attendance next to 0 completed. Both now read class dates."""
    db = _payroll_db()
    await db["sessions"].insert_one(
        {"session_id": "sess-1", "academy_id": "acad", "status": "scheduled", "capacity": 12}
    )
    await db["session_occurrences"].insert_many(
        [
            {
                "occurrence_id": f"occ-{day}",
                "academy_id": "acad",
                "session_id": "sess-1",
                "status": "scheduled",  # nothing writes "completed"
                "start_at": datetime(2026, 5, day, 14, tzinfo=UTC),
                "end_at": datetime(2026, 5, day, 15, tzinfo=UTC),
            }
            for day in (2, 9, 16)
        ]
        + [
            {
                "occurrence_id": "occ-june",
                "academy_id": "acad",
                "session_id": "sess-1",
                "status": "scheduled",
                "start_at": datetime(2026, 6, 6, 14, tzinfo=UTC),
                "end_at": datetime(2026, 6, 6, 15, tzinfo=UTC),
            }
        ]
    )
    await db["attendance"].insert_many(
        [
            # May class marked late, in June: counts in May.
            {
                "academy_id": "acad",
                "occurrence_id": "occ-16",
                "status": "present",
                "marked_at": datetime(2026, 6, 2, tzinfo=UTC),
            },
            {
                "academy_id": "acad",
                "occurrence_id": "occ-2",
                "status": "absent",
                "marked_at": datetime(2026, 5, 2, tzinfo=UTC),
            },
            # June class marked early, in May: not May attendance.
            {
                "academy_id": "acad",
                "occurrence_id": "occ-june",
                "status": "present",
                "marked_at": datetime(2026, 5, 31, tzinfo=UTC),
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "enrollment_id": f"enr-{i}",
                "academy_id": "acad",
                "session_id": "sess-1",
                "status": "active",
            }
            for i in range(9)
        ]
        + [
            {
                "enrollment_id": "enr-free",
                "academy_id": "acad",
                "session_id": "sess-1",
                "status": "active",
                "billing_type": "NoCharge",
            },
            {
                "enrollment_id": "enr-waived",
                "academy_id": "acad",
                "session_id": "sess-1",
                "status": "active",
                "billing_type": "Waived",
            },
        ]
    )

    dashboard = await _dashboard(db)

    assert dashboard["sessions"]["completed_count"] == 3
    assert dashboard["sessions"]["scheduled_count"] == 0
    assert dashboard["sessions"]["enrolled_seats"] == 11
    assert dashboard["sessions"]["paying_seats"] == 9
    assert dashboard["attendance"]["recorded_count"] == 2
    assert dashboard["attendance"]["present_count"] == 1
