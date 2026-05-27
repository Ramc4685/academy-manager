"""Mongo-backed admin student directory contract tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
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
    await db["payments"].insert_one({"payment_id": "pay-1", **historical})
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
    payment = await db["payments"].find_one({"academy_id": acad, "payment_id": "pay-1"})
    waiver = await db["waiver_acceptances"].find_one(
        {"academy_id": acad, "acceptance_id": "waiver-1"}
    )
    credit = await db["account_credit_ledger"].find_one(
        {"academy_id": acad, "credit_id": "credit-1"}
    )
    waitlist = await db["waitlist"].find_one({"academy_id": acad, "waitlist_id": "wait-1"})
    assert payment["parent_id"] == "parent-old"
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
