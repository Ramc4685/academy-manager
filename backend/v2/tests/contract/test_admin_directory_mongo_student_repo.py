"""Mongo-backed admin student directory contract tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    MAX_ACTIVE_SESSION_NAMES,
    AdminStudentCursor,
    ChangeAdminStudentParentCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    StudentParentInactive,
    StudentParentInvalidRole,
    StudentParentNotFound,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)


def _decode_cursor(cursor: str) -> dict[str, str]:
    padded = cursor + ("=" * (-len(cursor) % 4))
    return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())


async def _seed_directory(db, academy_id: str) -> datetime:
    now = datetime.now(UTC)
    await db["students"].insert_many(
        [
            {
                "academy_id": academy_id,
                "student_id": "st-bob",
                "full_name": "  Bob   Smith ",
                "parent_id": "parent-2",
                "status": "inactive",
            },
            {
                "academy_id": academy_id,
                "student_id": "st-alice",
                "full_name": "Alice Chen",
                "parent_id": "parent-1",
                "status": "active",
            },
            {
                "academy_id": academy_id,
                "student_id": "st-alana",
                "first_name": "Alana",
                "last_name": "Rivera",
                "parent_id": "parent-1",
                "status": "active",
            },
        ]
    )
    await db["users"].insert_many(
        [
            {
                "academy_id": academy_id,
                "user_id": "parent-1",
                "display_name": "Parent One",
                "email": "parent1@example.com",
            },
            {
                "academy_id": academy_id,
                "user_id": "parent-2",
                "display_name": "Parent Two",
                "email": "parent2@example.com",
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": academy_id,
                "enrollment_id": "enr-1",
                "student_id": "st-alice",
                "status": "active",
            },
            {
                "academy_id": academy_id,
                "enrollment_id": "enr-2",
                "student_id": "st-alice",
                "status": "paused",
            },
            {
                "academy_id": academy_id,
                "enrollment_id": "enr-3",
                "student_id": "st-bob",
                "status": "cancelled",
            },
        ]
    )
    await db["attendance"].insert_many(
        [
            {
                "academy_id": academy_id,
                "attendance_id": "att-1",
                "session_id": "sess-1",
                "student_id": "st-alice",
                "marked_at": now - timedelta(days=3),
                "status": "present",
            },
            {
                "academy_id": academy_id,
                "attendance_id": "att-2",
                "session_id": "sess-2",
                "student_id": "st-alice",
                "marked_at": now - timedelta(days=2),
                "status": "late",
            },
            {
                "academy_id": academy_id,
                "attendance_id": "att-3",
                "session_id": "sess-3",
                "student_id": "st-alice",
                "marked_at": now - timedelta(days=1),
                "status": "absent",
            },
        ]
    )
    await db["payments"].insert_many(
        [
            {
                "academy_id": academy_id,
                "payment_id": "pay-current",
                "student_id": "st-alice",
                "parent_id": "parent-1",
                "amount_cents": 1000,
                "status": "succeeded",
                "created_at": now - timedelta(days=5),
            },
            {
                "academy_id": academy_id,
                "payment_id": "pay-due",
                "student_id": "st-bob",
                "parent_id": "parent-2",
                "amount_cents": 1000,
                "status": "pending",
                "due_at": now + timedelta(days=5),
                "created_at": now - timedelta(days=1),
            },
            {
                "academy_id": academy_id,
                "payment_id": "pay-overdue",
                "student_id": "st-alana",
                "parent_id": "parent-1",
                "amount_cents": 1000,
                "status": "pending",
                "due_at": now - timedelta(days=1),
                "created_at": now - timedelta(days=10),
            },
        ]
    )
    return now


@pytest.mark.asyncio
async def test_list_admin_students_returns_rich_default_page_without_per_student_fanout(
    db, acad, monkeypatch
) -> None:
    seeded_now = await _seed_directory(db, acad)

    async def forbidden(*_, **__):  # pragma: no cover - assertion aid
        raise AssertionError("admin directory must use batched enrichment queries")

    monkeypatch.setattr(db["enrollments"], "count_documents", forbidden)
    monkeypatch.setattr(db["attendance"], "find_one", forbidden)

    repo = MongoStudentRepository(db)
    page = await repo.list_admin_students(
        search=None,
        status=None,
        limit=50,
        cursor=None,
    )

    assert [s.student_id for s in page.students] == ["st-alana", "st-alice", "st-bob"]
    alana, alice, bob = page.students
    assert page.next_cursor is None
    assert alana.full_name == "Alana Rivera"
    assert alana.dues_status == "overdue"
    assert alice.parent_name == "Parent One"
    assert alice.parent_email == "parent1@example.com"
    assert alice.active_session_count == 1
    assert alice.attendance_rate == pytest.approx(2 / 3)
    _expected_last_seen = (seeded_now - timedelta(days=1)).replace(
        microsecond=(seeded_now.microsecond // 1000) * 1000
    )
    assert alice.last_seen_at == _expected_last_seen
    assert alice.dues_status == "current"
    assert bob.attendance_rate is None
    assert bob.last_seen_at is None
    assert bob.dues_status == "due"


@pytest.mark.asyncio
async def test_list_admin_students_uses_ledger_invoice_balances_for_dues_status(db, acad) -> None:
    now = datetime.now(UTC)
    await db["students"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": "st-current",
                "full_name": "Current Student",
                "parent_id": "parent-1",
                "status": "active",
            },
            {
                "academy_id": acad,
                "student_id": "st-due",
                "full_name": "Due Student",
                "parent_id": "parent-1",
                "status": "active",
            },
            {
                "academy_id": acad,
                "student_id": "st-overdue",
                "full_name": "Overdue Student",
                "parent_id": "parent-1",
                "status": "active",
            },
        ]
    )
    await db["invoices"].insert_many(
        [
            {
                "academy_id": acad,
                "invoice_id": "inv-current-paid",
                "student_id": "st-current",
                "parent_id": "parent-1",
                "period": "2026-06",
                "status": "paid",
                "total_cents": 1000,
                "balance_due_cents": 0,
                "created_at": now,
                "due_date": now - timedelta(days=10),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-due",
                "student_id": "st-due",
                "parent_id": "parent-1",
                "period": "2026-06",
                "status": "open",
                "total_cents": 1000,
                "balance_due_cents": 1000,
                "created_at": now,
                "due_date": now + timedelta(days=5),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-overdue",
                "student_id": "st-overdue",
                "parent_id": "parent-1",
                "period": "2026-06",
                "status": "open",
                "total_cents": 1000,
                "balance_due_cents": 1000,
                "created_at": now,
                "due_date": now - timedelta(days=1),
            },
        ]
    )

    page = await MongoStudentRepository(db).list_admin_students(
        search=None,
        status=None,
        limit=50,
        cursor=None,
    )

    dues = {student.student_id: student.dues_status for student in page.students}
    assert dues == {
        "st-current": "current",
        "st-due": "due",
        "st-overdue": "overdue",
    }


@pytest.mark.asyncio
async def test_list_admin_students_filters_search_and_status(db, acad) -> None:
    await _seed_directory(db, acad)
    repo = MongoStudentRepository(db)

    page = await repo.list_admin_students(
        search="alice",
        status="active",
        limit=50,
        cursor=None,
    )

    assert [s.student_id for s in page.students] == ["st-alice"]


@pytest.mark.asyncio
async def test_list_admin_students_missing_filter_returns_only_incomplete(db, acad) -> None:
    """Issue #380 admin gap report: none of the three seeded students has an
    emergency contact, so all three match; only st-bob has no DOB either."""
    await _seed_directory(db, acad)
    repo = MongoStudentRepository(db)

    page = await repo.list_admin_students(
        search=None,
        status=None,
        limit=50,
        cursor=None,
        missing=("date_of_birth",),
    )

    assert {s.student_id for s in page.students} == {"st-bob", "st-alice", "st-alana"}


@pytest.mark.asyncio
async def test_list_admin_students_missing_filter_rejects_unknown_key(db, acad) -> None:
    await _seed_directory(db, acad)
    repo = MongoStudentRepository(db)

    with pytest.raises(ValueError, match="status"):
        await repo.list_admin_students(
            search=None,
            status=None,
            limit=50,
            cursor=None,
            missing=("status",),  # not a completeness field — must be rejected
        )


@pytest.mark.asyncio
async def test_list_admin_students_missing_filter_excludes_complete_students(db, acad) -> None:
    await _seed_directory(db, acad)
    await db["students"].update_one(
        {"student_id": "st-alice"},
        {
            "$set": {
                "date_of_birth": "2015-04-02",
                "emergency_contact_name": "Someone",
                "emergency_contact_phone": "+1 555 0111",
                "medical_notes": "__none_declared__",
            }
        },
    )
    repo = MongoStudentRepository(db)

    page = await repo.list_admin_students(
        search=None,
        status=None,
        limit=50,
        cursor=None,
        missing=("date_of_birth", "emergency_contact_name"),
    )

    assert "st-alice" not in {s.student_id for s in page.students}
    assert {s.student_id for s in page.students} == {"st-bob", "st-alana"}


@pytest.mark.asyncio
async def test_list_admin_students_cursor_returns_next_page_and_opaque_next_cursor(
    db, acad
) -> None:
    await _seed_directory(db, acad)
    repo = MongoStudentRepository(db)

    first = await repo.list_admin_students(
        search=None,
        status=None,
        limit=2,
        cursor=None,
    )
    cursor = AdminStudentCursor(full_name_key="alice chen", student_id="st-alice")
    second = await repo.list_admin_students(
        search=None,
        status=None,
        limit=2,
        cursor=base64.urlsafe_b64encode(
            json.dumps(cursor.model_dump(), separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("="),
    )

    assert [s.student_id for s in first.students] == ["st-alana", "st-alice"]
    assert _decode_cursor(first.next_cursor or "") == {
        "full_name_key": "alice chen",
        "student_id": "st-alice",
    }
    assert [s.student_id for s in second.students] == ["st-bob"]
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_get_admin_student_enriches_sessions_payments_and_current_invoice(db, acad) -> None:
    now = datetime.now(UTC)
    await db["students"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": "st-alice",
                "full_name": "Alice Chen",
                "parent_id": "parent-1",
                "status": "active",
                "skill_level": "intermediate",
                "previous_experience": "Two years of club play",
                "medical_notes": "Peanut allergy",
                "emergency_contact_name": "Anita Chen",
                "emergency_contact_phone": "555-0199",
                "t_shirt_size": "M",
            },
            {
                "academy_id": acad,
                "student_id": "st-bob",
                "full_name": "Bob Rao",
                "parent_id": "parent-2",
                "status": "active",
            },
            {
                "academy_id": "other-academy",
                "student_id": "st-alice",
                "full_name": "Other Alice",
                "parent_id": "parent-other",
                "status": "active",
            },
        ]
    )
    await db["sessions"].insert_many(
        [
            {
                "academy_id": acad,
                "session_id": "sess-active",
                "title": "Advanced Footwork",
                "location": "Court 1",
                "coach_id": "coach-1",
                "start_at": now + timedelta(days=2),
                "end_at": now + timedelta(days=2, hours=1),
                "capacity": 8,
                "status": "scheduled",
                "amount_cents": 15_000,
            },
            {
                "academy_id": "other-academy",
                "session_id": "sess-other",
                "title": "Other Tenant Session",
                "location": "Court X",
                "start_at": now + timedelta(days=3),
                "end_at": now + timedelta(days=3, hours=1),
                "status": "scheduled",
                "amount_cents": 99_000,
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "enr-active",
                "student_id": "st-alice",
                "session_id": "sess-active",
                "status": "active",
                "payment_mode": "monthly",
                "subscription_status": "active",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-other-student",
                "student_id": "st-bob",
                "session_id": "sess-active",
                "status": "active",
            },
            {
                "academy_id": "other-academy",
                "enrollment_id": "enr-other-tenant",
                "student_id": "st-alice",
                "session_id": "sess-other",
                "status": "active",
            },
        ]
    )
    await db["payments"].insert_many(
        [
            {
                "academy_id": acad,
                "payment_id": "pay-paid",
                "student_id": "st-alice",
                "session_id": "sess-active",
                "period": "2026-05",
                "amount_cents": 15_000,
                "paid_amount_cents": 15_000,
                "balance_due_cents": 0,
                "status": "paid",
                "payment_method": "card",
                "created_at": now - timedelta(days=10),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-stripe-subscription",
                "enrollment_id": "enr-active",
                "parent_id": "parent-1",
                "session_id": "sess-active",
                "period": "2026-07",
                "amount_cents": 15_000,
                "status": "succeeded",
                "payment_method": "stripe",
                "created_at": now - timedelta(hours=1),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-open",
                "student_id": "st-alice",
                "session_id": "sess-active",
                "period": "2026-06",
                "amount_cents": 15_000,
                "paid_amount_cents": 4_000,
                "balance_due_cents": 11_000,
                "status": "partially_paid",
                "payment_method": "cash",
                "created_at": now - timedelta(days=1),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-open-older",
                "student_id": "st-alice",
                "session_id": "sess-active",
                "period": "2026-05",
                "amount_cents": 6_000,
                "paid_amount_cents": 0,
                "balance_due_cents": 6_000,
                "status": "unpaid",
                "payment_method": "invoice",
                "created_at": now - timedelta(days=2),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-other-student",
                "student_id": "st-bob",
                "session_id": "sess-active",
                "period": "2026-06",
                "amount_cents": 99_000,
                "status": "unpaid",
                "created_at": now,
            },
            {
                "academy_id": "other-academy",
                "payment_id": "pay-other-tenant",
                "student_id": "st-alice",
                "session_id": "sess-other",
                "period": "2026-06",
                "amount_cents": 99_000,
                "status": "unpaid",
                "created_at": now,
            },
        ]
    )
    await db["waiver_versions"].insert_one(
        {
            "academy_id": acad,
            "waiver_version_id": "waiver-2026",
            "version": "2026-v1",
        }
    )
    await db["waiver_acceptances"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-alice",
            "waiver_version_id": "waiver-2026",
            "accepted_at": now - timedelta(days=20),
        }
    )
    await db["attendance"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": "st-alice",
                "session_id": "sess-active",
                "date": "2026-05-18",
                "status": "present",
                "marked_at": now - timedelta(days=3),
            },
            {
                "academy_id": acad,
                "student_id": "st-alice",
                "session_id": "sess-active",
                "date": "2026-05-11",
                "status": "absent",
                "marked_at": now - timedelta(days=10),
            },
            {
                "academy_id": "other-academy",
                "student_id": "st-alice",
                "session_id": "sess-other",
                "date": "2026-05-20",
                "status": "present",
                "marked_at": now,
            },
        ]
    )

    repo = MongoStudentRepository(db)
    detail = await repo.get_admin_student("st-alice")

    assert detail is not None
    assert detail.level == "intermediate"
    assert detail.previous_experience == "Two years of club play"
    assert detail.medical_notes == "Peanut allergy"
    assert detail.emergency_contact_name == "Anita Chen"
    assert detail.emergency_contact_phone == "555-0199"
    assert detail.t_shirt_size == "M"
    assert detail.waiver_status == "signed"
    assert detail.waiver_signed_at is not None
    assert detail.waiver_version == "2026-v1"
    assert [row.status for row in detail.recent_attendance] == ["present", "absent"]
    assert [row.enrollment_id for row in detail.enrolled_sessions] == ["enr-active"]
    assert detail.enrolled_sessions[0].session_id == "sess-active"
    assert detail.enrolled_sessions[0].session_title == "Advanced Footwork"
    assert detail.enrolled_sessions[0].location == "Court 1"
    assert detail.enrolled_sessions[0].status == "active"
    assert detail.enrolled_sessions[0].payment_mode == "monthly"
    assert detail.enrolled_sessions[0].subscription_status == "active"
    assert detail.enrolled_sessions[0].amount_cents == 15_000
    assert [row.payment_id for row in detail.payment_history] == [
        "pay-stripe-subscription",
        "pay-open",
        "pay-open-older",
        "pay-paid",
    ]
    assert detail.payment_history[0].balance_due_cents == 0
    assert detail.payment_history[0].payment_method == "stripe"
    assert detail.payment_history[1].balance_due_cents == 11_000
    assert detail.payment_history[1].payment_method == "cash"
    assert detail.payment_history[2].balance_due_cents == 6_000
    assert detail.outstanding_balance_cents == 17_000
    assert detail.current_payment is not None
    assert detail.current_payment.payment_id == "pay-open"
    assert detail.current_payment.session_id == "sess-active"
    assert detail.current_payment.period == "2026-06"
    assert detail.current_payment.amount_cents == 11_000
    assert detail.current_payment.source == "invoice"
    assert detail.current_payment.status == "partially_paid"


@pytest.mark.asyncio
async def test_get_admin_student_marks_missing_waiver(db, acad) -> None:
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-missing",
            "full_name": "Mira Patel",
            "parent_id": "parent-1",
            "status": "active",
        }
    )

    detail = await MongoStudentRepository(db).get_admin_student("st-missing")

    assert detail is not None
    assert detail.waiver_status == "missing"
    assert detail.recent_attendance == []


@pytest.mark.asyncio
async def test_get_admin_student_normalizes_legacy_payment_amounts(db, acad) -> None:
    now = datetime.now(UTC)
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-alice",
            "full_name": "Alice Chen",
            "parent_id": "parent-1",
            "status": "active",
        }
    )
    await db["payments"].insert_many(
        [
            {
                "academy_id": acad,
                "payment_id": "pay-succeeded-implicit",
                "student_id": "st-alice",
                "period": "2026-03",
                "amount_cents": 10_000,
                "balance_due_cents": 10_000,
                "status": "succeeded",
                "created_at": now - timedelta(days=4),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-paid-stale-balance",
                "student_id": "st-alice",
                "period": "2026-03",
                "amount_cents": 9_000,
                "balance_due_cents": 9_000,
                "status": "paid",
                "created_at": now - timedelta(days=5),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-discounted",
                "student_id": "st-alice",
                "period": "2026-04",
                "amount_cents": 15_000,
                "discount_cents": 5_000,
                "status": "unpaid",
                "created_at": now - timedelta(days=3),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-expired",
                "student_id": "st-alice",
                "period": "2026-05",
                "amount_cents": 12_000,
                "status": "expired",
                "created_at": now - timedelta(days=2),
            },
            {
                "academy_id": acad,
                "payment_id": "pay-failed-final",
                "student_id": "st-alice",
                "period": "2026-06",
                "amount_cents": 20_000,
                "final_amount_cents": 8_000,
                "amount_received_cents": 3_000,
                "status": "failed",
                "created_at": now - timedelta(days=1),
            },
        ]
    )

    repo = MongoStudentRepository(db)
    detail = await repo.get_admin_student("st-alice")

    assert detail is not None
    payments = {row.payment_id: row for row in detail.payment_history}
    assert payments["pay-succeeded-implicit"].amount_cents == 10_000
    assert payments["pay-succeeded-implicit"].paid_amount_cents == 10_000
    assert payments["pay-succeeded-implicit"].balance_due_cents == 0
    assert payments["pay-paid-stale-balance"].amount_cents == 9_000
    assert payments["pay-paid-stale-balance"].paid_amount_cents == 9_000
    assert payments["pay-paid-stale-balance"].balance_due_cents == 0
    assert payments["pay-discounted"].amount_cents == 10_000
    assert payments["pay-discounted"].paid_amount_cents == 0
    assert payments["pay-discounted"].balance_due_cents == 10_000
    assert payments["pay-expired"].balance_due_cents == 12_000
    assert payments["pay-failed-final"].amount_cents == 8_000
    assert payments["pay-failed-final"].paid_amount_cents == 3_000
    assert payments["pay-failed-final"].balance_due_cents == 5_000
    assert detail.current_payment is not None
    assert detail.current_payment.payment_id == "pay-failed-final"
    assert detail.current_payment.amount_cents == 5_000
    assert detail.current_payment.status == "failed"
    assert detail.current_payment.source == "invoice"


@pytest.mark.asyncio
async def test_get_admin_student_current_payment_none_when_all_paid_no_open_invoice(
    db, acad
) -> None:
    now = datetime.now(UTC)
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-alice",
            "full_name": "Alice Chen",
            "parent_id": "parent-1",
            "status": "active",
        }
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-active",
            "title": "Beginner Group",
            "location": "Court 2",
            "start_at": now + timedelta(days=5),
            "end_at": now + timedelta(days=5, hours=1),
            "status": "scheduled",
            "monthly_price_cents": 12_500,
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enr-active",
            "student_id": "st-alice",
            "session_id": "sess-active",
            "status": "active",
        }
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-paid",
            "student_id": "st-alice",
            "session_id": "sess-active",
            "period": "2026-05",
            "amount_cents": 12_500,
            "paid_amount_cents": 12_500,
            "status": "paid",
            "created_at": now - timedelta(days=20),
        }
    )

    repo = MongoStudentRepository(db)
    detail = await repo.get_admin_student("st-alice")

    assert detail is not None
    # No open invoice and no unpaid payment → current_payment is None.
    # The "session_price" fallback (showing enrollment price) was removed in Phase 3.
    assert detail.current_payment is None


@pytest.mark.asyncio
async def test_get_admin_student_preserves_zero_enrollment_fee_override(db, acad) -> None:
    now = datetime.now(UTC)
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-alice",
            "full_name": "Alice Chen",
            "parent_id": "parent-1",
            "status": "active",
        }
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-active",
            "title": "Beginner Group",
            "location": "Court 2",
            "start_at": now + timedelta(days=5),
            "end_at": now + timedelta(days=5, hours=1),
            "status": "scheduled",
            "monthly_price_cents": 12_500,
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enr-active",
            "student_id": "st-alice",
            "session_id": "sess-active",
            "status": "active",
            "amount_cents": 0,
            "final_amount_cents": 0,
        }
    )

    repo = MongoStudentRepository(db)
    detail = await repo.get_admin_student("st-alice")

    assert detail is not None
    assert detail.enrolled_sessions[0].amount_cents == 0


@pytest.mark.asyncio
async def test_get_admin_student_includes_enrollment_linked_paid_ledger_invoice_once(
    db, acad
) -> None:
    now = datetime.now(UTC)
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-alice",
            "full_name": "Alice Chen",
            "parent_id": "parent-1",
            "status": "active",
        }
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-active",
            "title": "Beginner Group",
            "location": "Court 2",
            "start_at": now + timedelta(days=5),
            "end_at": now + timedelta(days=5, hours=1),
            "status": "scheduled",
            "monthly_price_cents": 7_000,
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enr-active",
            "student_id": "st-alice",
            "session_id": "sess-active",
            "status": "active",
        }
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "legacy-projection",
            "student_id": "st-alice",
            "enrollment_id": "enr-active",
            "period": "2026-06",
            "amount_cents": 7_000,
            "paid_amount_cents": 7_000,
            "balance_due_cents": 0,
            "status": "succeeded",
            "payment_method": "stripe_subscription",
            "stripe_payment_intent_id": "in_subscription_paid",
            "created_at": now - timedelta(minutes=1),
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "ledger-invoice-paid",
            "parent_id": "parent-1",
            "enrollment_id": "enr-active",
            "period": "2026-06",
            "status": "paid",
            "subtotal_cents": 7_000,
            "discount_cents": 0,
            "total_cents": 7_000,
            "balance_due_cents": 0,
            "currency": "usd",
            "due_date": now,
            "stripe_invoice_id": "in_subscription_paid",
            "created_at": now,
            "updated_at": now,
        }
    )

    detail = await MongoStudentRepository(db).get_admin_student("st-alice")

    assert detail is not None
    assert [row.payment_id for row in detail.payment_history] == ["ledger-invoice-paid"]
    assert detail.payment_history[0].stripe_invoice_id == "in_subscription_paid"
    assert detail.payment_history[0].balance_due_cents == 0
    assert detail.current_payment is None


async def _seed_parent_change(db, academy_id: str) -> None:
    await db["students"].insert_one(
        {
            "academy_id": academy_id,
            "student_id": "st-alice",
            "full_name": "Alice Chen",
            "parent_id": "parent-old",
            "parent_user_id": "parent-old",
            "status": "active",
        }
    )
    await db["users"].insert_many(
        [
            {
                "academy_id": academy_id,
                "user_id": "parent-old",
                "display_name": "Parent Old",
                "email": "old@example.com",
                "role": "parent",
                "roles": ["parent"],
                "status": "active",
                "is_active": True,
            },
            {
                "academy_id": academy_id,
                "user_id": "parent-new",
                "firebase_uid": "firebase-new",
                "display_name": "Parent New",
                "email": "new@example.com",
                "phone": "555-0202",
                "roles": ["parent"],
                "status": "active",
                "is_active": True,
            },
            {
                "academy_id": academy_id,
                "user_id": "coach-1",
                "display_name": "Coach One",
                "email": "coach@example.com",
                "roles": ["coach"],
                "status": "active",
                "is_active": True,
            },
            {
                "academy_id": academy_id,
                "user_id": "parent-inactive",
                "display_name": "Inactive Parent",
                "email": "inactive@example.com",
                "roles": ["parent"],
                "status": "inactive",
                "is_active": False,
            },
            {
                "academy_id": "other-academy",
                "user_id": "parent-other",
                "display_name": "Other Parent",
                "email": "other@example.com",
                "roles": ["parent"],
                "status": "active",
                "is_active": True,
            },
        ]
    )
    historical = {
        "academy_id": academy_id,
        "student_id": "st-alice",
        "parent_id": "parent-old",
        "parent_user_id": "parent-old",
    }
    await db["invoices"].insert_one({"invoice_id": "inv-1", **historical})
    await db["waiver_acceptances"].insert_one({"acceptance_id": "waiver-1", **historical})
    await db["account_credit_ledger"].insert_one({"credit_id": "credit-1", **historical})
    await db["waitlist"].insert_one({"waitlist_id": "wait-1", **historical})


@pytest.mark.asyncio
async def test_change_student_parent_updates_only_student_fields_and_writes_audit(db, acad) -> None:
    await _seed_parent_change(db, acad)
    repo = MongoStudentRepository(db)

    result = await repo.change_admin_student_parent(
        "st-alice",
        ChangeAdminStudentParentCommand(
            parent_id="firebase-new",
            actor_id="admin-1",
            reason="Custody update",
        ),
    )

    assert result is not None
    assert result.parent.parent_id == "parent-new"
    assert result.parent.email == "new@example.com"
    assert result.parent.phone == "555-0202"
    assert result.previous_parent_id == "parent-old"
    assert result.impact_counts == {
        "payments": 1,
        "waivers": 1,
        "credits": 1,
        "waitlist": 1,
    }
    student = await db["students"].find_one({"academy_id": acad, "student_id": "st-alice"})
    assert student["parent_id"] == "parent-new"
    assert student["parent_user_id"] == "parent-new"
    invoice = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-1"})
    waiver = await db["waiver_acceptances"].find_one(
        {"academy_id": acad, "acceptance_id": "waiver-1"}
    )
    credit = await db["account_credit_ledger"].find_one(
        {"academy_id": acad, "credit_id": "credit-1"}
    )
    waitlist = await db["waitlist"].find_one({"academy_id": acad, "waitlist_id": "wait-1"})
    assert invoice["parent_id"] == "parent-old"
    assert waiver["parent_user_id"] == "parent-old"
    assert credit["parent_id"] == "parent-old"
    assert waitlist["parent_id"] == "parent-old"
    audit = await db["audit_logs"].find_one(
        {"academy_id": acad, "action": "student.parent_changed"}
    )
    assert audit is not None
    assert audit["actor_id"] == "admin-1"
    assert audit["reason"] == "Custody update"
    assert audit["old_parent_id"] == "parent-old"
    assert audit["new_parent_id"] == "parent-new"
    assert audit["entity_id"] == "st-alice"
    assert isinstance(audit["created_at"], datetime)


@pytest.mark.asyncio
async def test_change_student_parent_rejects_non_parent_inactive_and_cross_tenant(db, acad) -> None:
    await _seed_parent_change(db, acad)
    repo = MongoStudentRepository(db)

    with pytest.raises(StudentParentInvalidRole):
        await repo.change_admin_student_parent(
            "st-alice",
            ChangeAdminStudentParentCommand(
                parent_id="coach-1",
                actor_id="admin-1",
                reason="Custody update",
            ),
        )

    with pytest.raises(StudentParentInactive):
        await repo.change_admin_student_parent(
            "st-alice",
            ChangeAdminStudentParentCommand(
                parent_id="parent-inactive",
                actor_id="admin-1",
                reason="Custody update",
            ),
        )

    with pytest.raises(StudentParentNotFound):
        await repo.change_admin_student_parent(
            "st-alice",
            ChangeAdminStudentParentCommand(
                parent_id="parent-other",
                actor_id="admin-1",
                reason="Custody update",
            ),
        )


async def _seed_student_with_sessions(
    db,
    academy_id: str,
    *,
    student_id: str,
    session_titles: dict[str, str],
    enrolled: list[tuple[str, str]],
) -> None:
    """Seed one student plus sessions and enrollments.

    ``enrolled`` is a list of ``(session_id, status)`` pairs; ``session_titles``
    maps session_id -> title for the session documents to create (a session id
    used in ``enrolled`` but absent here is left dangling on purpose).
    """
    await db["students"].insert_one(
        {
            "academy_id": academy_id,
            "student_id": student_id,
            "full_name": f"Student {student_id}",
            "parent_id": "parent-1",
            "status": "active",
        }
    )
    if session_titles:
        await db["sessions"].insert_many(
            [
                {"academy_id": academy_id, "session_id": session_id, "title": title}
                for session_id, title in session_titles.items()
            ]
        )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": academy_id,
                "enrollment_id": f"enr-{student_id}-{index}",
                "student_id": student_id,
                "session_id": session_id,
                "status": status,
            }
            for index, (session_id, status) in enumerate(enrolled)
        ]
    )


@pytest.mark.asyncio
async def test_list_admin_students_returns_active_session_names(db, acad) -> None:
    """Issue #104: the directory names the sessions, not just how many."""
    await _seed_student_with_sessions(
        db,
        acad,
        student_id="st-named",
        session_titles={
            "sess-a": "Wednesday 6 PM Beginner",
            "sess-b": "Saturday 9 AM Intermediate",
            "sess-old": "Retired Session",
        },
        enrolled=[("sess-a", "active"), ("sess-b", "active"), ("sess-old", "cancelled")],
    )

    repo = MongoStudentRepository(db)
    page = await repo.list_admin_students(search=None, status=None, limit=50, cursor=None)
    student = next(s for s in page.students if s.student_id == "st-named")

    assert student.active_session_count == 2
    assert student.active_session_total == 2
    assert student.active_session_names == [
        "Saturday 9 AM Intermediate",
        "Wednesday 6 PM Beginner",
    ]
    # Cancelled enrollments contribute neither a count nor a name.
    assert "Retired Session" not in student.active_session_names


@pytest.mark.asyncio
async def test_list_admin_students_caps_active_session_names(db, acad) -> None:
    """A student in many sessions must not blow up the row or the payload."""
    titles = {f"sess-{i}": f"Session {i:02d}" for i in range(6)}
    await _seed_student_with_sessions(
        db,
        acad,
        student_id="st-many",
        session_titles=titles,
        enrolled=[(session_id, "active") for session_id in titles],
    )

    repo = MongoStudentRepository(db)
    page = await repo.list_admin_students(search=None, status=None, limit=50, cursor=None)
    student = next(s for s in page.students if s.student_id == "st-many")

    assert student.active_session_count == 6
    assert student.active_session_total == 6
    assert len(student.active_session_names) == MAX_ACTIVE_SESSION_NAMES
    # Deterministic truncation, so the row does not reshuffle between requests.
    assert student.active_session_names == ["Session 00", "Session 01", "Session 02"]


@pytest.mark.asyncio
async def test_list_admin_students_without_active_sessions_returns_no_names(db, acad) -> None:
    await _seed_student_with_sessions(
        db,
        acad,
        student_id="st-none",
        session_titles={"sess-x": "Paused Session"},
        enrolled=[("sess-x", "paused")],
    )

    repo = MongoStudentRepository(db)
    page = await repo.list_admin_students(search=None, status=None, limit=50, cursor=None)
    student = next(s for s in page.students if s.student_id == "st-none")

    assert student.active_session_count == 0
    assert student.active_session_total == 0
    assert student.active_session_names == []


@pytest.mark.asyncio
async def test_list_admin_students_falls_back_for_missing_session_document(db, acad) -> None:
    """A dangling session_id still counts, and reads as a generic session."""
    await _seed_student_with_sessions(
        db,
        acad,
        student_id="st-dangling",
        session_titles={},
        enrolled=[("sess-gone", "active")],
    )

    repo = MongoStudentRepository(db)
    page = await repo.list_admin_students(search=None, status=None, limit=50, cursor=None)
    student = next(s for s in page.students if s.student_id == "st-dangling")

    assert student.active_session_count == 1
    assert student.active_session_names == ["Academy session"]


@pytest.mark.asyncio
async def test_list_admin_students_does_not_leak_session_names_across_tenants(db, acad) -> None:
    await _seed_student_with_sessions(
        db,
        acad,
        student_id="st-tenant",
        session_titles={},
        enrolled=[("sess-other", "active")],
    )
    await db["sessions"].insert_one(
        {"academy_id": "other-academy", "session_id": "sess-other", "title": "Other Tenant Session"}
    )

    repo = MongoStudentRepository(db)
    page = await repo.list_admin_students(search=None, status=None, limit=50, cursor=None)
    student = next(s for s in page.students if s.student_id == "st-tenant")

    assert student.active_session_names == ["Academy session"]


@pytest.mark.asyncio
async def test_list_admin_students_total_counts_distinct_sessions_not_enrollments(db, acad) -> None:
    """Two active enrollments for one session are one session, not two.

    Nothing in the schema prevents this — migration 0010 makes only
    ``enrollment_id`` unique — and ``active_session_count`` counts enrollment
    documents, so the directory must not render "+1 more" beside the single
    name it actually has.
    """
    await _seed_student_with_sessions(
        db,
        acad,
        student_id="st-dupe",
        session_titles={"sess-dupe": "Monday 5 PM Juniors"},
        enrolled=[("sess-dupe", "active"), ("sess-dupe", "active")],
    )

    repo = MongoStudentRepository(db)
    page = await repo.list_admin_students(search=None, status=None, limit=50, cursor=None)
    student = next(s for s in page.students if s.student_id == "st-dupe")

    assert student.active_session_count == 2
    assert student.active_session_total == 1
    assert student.active_session_names == ["Monday 5 PM Juniors"]
    # total == len(names) means the UI has nothing left to summarise.
    assert student.active_session_total == len(student.active_session_names)


@pytest.mark.asyncio
async def test_get_admin_student_reports_distinct_active_session_total(db, acad) -> None:
    await _seed_student_with_sessions(
        db,
        acad,
        student_id="st-detail",
        session_titles={"sess-d1": "Tuesday Drills", "sess-d2": "Thursday Drills"},
        enrolled=[("sess-d1", "active"), ("sess-d2", "active"), ("sess-d1", "cancelled")],
    )

    repo = MongoStudentRepository(db)
    detail = await repo.get_admin_student("st-detail")

    assert detail is not None
    assert detail.active_session_total == 2
    assert detail.active_session_names == ["Thursday Drills", "Tuesday Drills"]
