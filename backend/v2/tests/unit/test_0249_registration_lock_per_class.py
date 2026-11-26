"""Migration 0249: pre-S48 registration locks gain the class, so the index races per class."""

from __future__ import annotations

import importlib

import mongomock_motor
import pytest
from pymongo.errors import DuplicateKeyError


async def _up(db, name: str) -> None:  # type: ignore[no-untyped-def]
    await importlib.import_module(f"backend.v2.migrations.{name}").up(db)


def _row(
    enrollment_id: str, status: str, lock: str | None, session: str = "sess-1"
) -> dict[str, object]:
    return {
        "academy_id": "acad-a",
        "enrollment_id": enrollment_id,
        "session_id": session,
        "student_id": "stu-1",
        "status": status,
        "registration_student_lock": lock,
    }


async def test_old_live_lock_blocks_a_racing_same_class_row_after_the_rewrite() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _up(db, "0147_registration_student_lock")
    await _up(db, "0185_registration_lock_non_terminal")
    await db.enrollments.insert_many(
        [
            _row("old-live", "active", "stu-1"),
            _row("old-ended", "cancelled", "stu-0", session="sess-9"),
            _row("new", "active", "stu-2|sess-2", session="sess-2"),
            _row("walk-in", "active", None),
        ]
    )

    await _up(db, "0249_registration_lock_per_class")
    await _up(db, "0249_registration_lock_per_class")  # idempotent

    locks = {
        d["enrollment_id"]: d["registration_student_lock"] async for d in db.enrollments.find()
    }
    assert locks == {
        "old-live": "stu-1|sess-1",
        "old-ended": "stu-0",
        "new": "stu-2|sess-2",
        "walk-in": None,
    }
    with pytest.raises(DuplicateKeyError):
        await db.enrollments.insert_one(_row("race", "active", "stu-1|sess-1"))
    # A second class for the same child is still allowed.
    await db.enrollments.insert_one(_row("second", "active", "stu-1|sess-3", session="sess-3"))
