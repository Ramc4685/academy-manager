"""Migration 0185 — the registration student lock covers every non-ended status.

0147 scoped ``uq_registration_active_student_lock`` to ``active``/``paused``,
written before ``held`` (#697) existed. #782 widened the application checks to
``NON_TERMINAL``; the database race backstop was left behind (#836).

mongomock enforces the ``status`` half of the partial filter (not ``$type``),
which is enough to pin the behaviour and not just the index definition.
"""

from __future__ import annotations

import importlib

import mongomock_motor
import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.domain.models import NON_TERMINAL

INDEX = "uq_registration_active_student_lock"


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module("backend.v2.migrations.0185_registration_lock_non_terminal")
    await mod.up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed_0147(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module("backend.v2.migrations.0147_registration_student_lock")
    await mod.up(db)


def _row(enrollment_id: str, status: str, lock: str | None = "stu-1") -> dict[str, object]:
    return {
        "academy_id": "acad-a",
        "enrollment_id": enrollment_id,
        "session_id": f"sess-{enrollment_id}",
        "student_id": "stu-1",
        "status": status,
        "registration_student_lock": lock,
    }


async def test_the_lock_now_names_every_non_terminal_status() -> None:
    db = _fresh_db()
    await _seed_0147(db)

    await _run(db)

    spec = (await db.enrollments.index_information())[INDEX]
    assert spec["unique"] is True
    assert [k for k, _ in spec["key"]] == ["academy_id", "registration_student_lock"]
    partial = spec["partialFilterExpression"]
    assert partial["registration_student_lock"] == {"$type": "string"}
    assert set(partial["status"]["$in"]) == set(NON_TERMINAL)
    assert "held" in partial["status"]["$in"]


async def test_a_held_child_is_invisible_to_the_lock_before_and_blocked_after() -> None:
    before = _fresh_db()
    await _seed_0147(before)
    await before.enrollments.insert_one(_row("enr-1", "held"))
    await before.enrollments.insert_one(_row("enr-2", "active"))  # the gap

    after = _fresh_db()
    await _seed_0147(after)
    await _run(after)
    await after.enrollments.insert_one(_row("enr-1", "held"))
    with pytest.raises(DuplicateKeyError):
        await after.enrollments.insert_one(_row("enr-2", "active"))


async def test_a_dropped_row_still_never_blocks_a_fresh_registration() -> None:
    db = _fresh_db()
    await _seed_0147(db)
    await _run(db)

    await db.enrollments.insert_one(_row("enr-1", "dropped"))
    await db.enrollments.insert_one(_row("enr-2", "active"))


async def test_it_also_builds_the_index_where_0147_never_ran_and_reruns_cleanly() -> None:
    db = _fresh_db()

    await _run(db)
    await _run(db)

    assert INDEX in await db.enrollments.index_information()


async def test_an_existing_live_duplicate_aborts_and_leaves_the_old_index() -> None:
    """A held + active pair for one child would make the create fail half-way."""
    db = _fresh_db()
    await _seed_0147(db)
    await db.enrollments.insert_one(_row("enr-1", "held"))
    await db.enrollments.insert_one(_row("enr-2", "active"))

    with pytest.raises(RuntimeError, match="stu-1"):
        await _run(db)

    spec = (await db.enrollments.index_information())[INDEX]
    assert set(spec["partialFilterExpression"]["status"]["$in"]) == {"active", "paused"}


async def test_ended_and_unlocked_rows_do_not_count_as_duplicates() -> None:
    # Asserted on the pre-flight itself: mongomock ignores the ``$type`` half
    # of the filter, so the unlocked (``None``) row cannot sit under the index.
    db = _fresh_db()
    await db.enrollments.insert_one(_row("enr-1", "dropped"))
    await db.enrollments.insert_one(_row("enr-2", "active"))
    await db.enrollments.insert_one(_row("enr-3", "active", lock=None))
    mod = importlib.import_module("backend.v2.migrations.0185_registration_lock_non_terminal")

    assert await mod._colliding_locks(db.enrollments) == []
