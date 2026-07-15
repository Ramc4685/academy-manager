"""Registration student lock migration contract."""

from __future__ import annotations

import importlib

import pytest
from pymongo.errors import DuplicateKeyError


@pytest.mark.asyncio
async def test_registration_student_lock_prevents_two_active_approval_artifacts(db, acad) -> None:
    migration = importlib.import_module("backend.v2.migrations.0147_registration_student_lock")
    await migration.up(db)
    base = {
        "academy_id": acad,
        "student_id": "student-1",
        "status": "active",
        "registration_student_lock": "student-1",
    }
    await db["enrollments"].insert_one(
        {**base, "enrollment_id": "enrollment-app-1", "session_id": "session-1"}
    )

    with pytest.raises(DuplicateKeyError):
        await db["enrollments"].insert_one(
            {**base, "enrollment_id": "enrollment-app-2", "session_id": "session-2"}
        )


@pytest.mark.asyncio
async def test_registration_student_lock_does_not_restrict_legacy_enrollments(db, acad) -> None:
    migration = importlib.import_module("backend.v2.migrations.0147_registration_student_lock")
    await migration.up(db)
    for enrollment_id in ("legacy-1", "legacy-2"):
        await db["enrollments"].insert_one(
            {
                "academy_id": acad,
                "enrollment_id": enrollment_id,
                "student_id": "student-1",
                "session_id": enrollment_id,
                "status": "active",
            }
        )

    assert await db["enrollments"].count_documents({"academy_id": acad}) == 2


@pytest.mark.asyncio
async def test_paused_registration_keeps_child_lock_for_safe_resume(db, acad) -> None:
    migration = importlib.import_module("backend.v2.migrations.0147_registration_student_lock")
    await migration.up(db)
    base = {
        "academy_id": acad,
        "student_id": "student-1",
        "registration_student_lock": "student-1",
    }
    await db["enrollments"].insert_one(
        {
            **base,
            "enrollment_id": "paused-enrollment",
            "session_id": "session-1",
            "status": "paused",
        }
    )

    with pytest.raises(DuplicateKeyError):
        await db["enrollments"].insert_one(
            {
                **base,
                "enrollment_id": "new-registration",
                "session_id": "session-2",
                "status": "active",
            }
        )
