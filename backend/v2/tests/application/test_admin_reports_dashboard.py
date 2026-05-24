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
                "amount_received_cents": 4_000,
                "balance_due_cents": 6_000,
                "final_amount_cents": 10_000,
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

    with tenant_scope("acad"):
        dashboard = await admin_composition._make_reports_dashboard(db)("2026-05")

    assert dashboard["period"] == "2026-05"
    assert dashboard["cash_collected_cents"] == 13_000
    assert dashboard["outstanding_dues_cents"] == 6_000
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
        "enrolled_seats": 3,
        "capacity": 12,
        "capacity_utilization": 0.25,
        "empty": False,
    }
    assert dashboard["empty_states"] == []


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
            "empty": True,
        },
        "empty_states": [
            "No collected payment rows found for this month.",
            "No attendance marks found for this month.",
            "No sessions found for this month.",
        ],
    }
