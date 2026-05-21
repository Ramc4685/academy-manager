"""Mongo-backed admin student directory contract tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentCursor,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)


def _decode_cursor(cursor: str) -> dict[str, str]:
    padded = cursor + ("=" * (-len(cursor) % 4))
    return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())


async def _seed_directory(db, academy_id: str) -> None:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
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


@pytest.mark.asyncio
async def test_list_admin_students_returns_rich_default_page_without_per_student_fanout(
    db, acad, monkeypatch
) -> None:
    await _seed_directory(db, acad)

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
    assert alice.last_seen_at == datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
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
