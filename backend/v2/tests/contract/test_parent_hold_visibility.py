"""Issue #740 — the parent read model must not hide a held enrollment.

A hold (#697) keeps the seat but stops attendance. The parent feed filtered
``{active, paused}``, so a held row was dropped before it ever reached the
BFF: the class simply disappeared from the Children page with no badge, no
return date, and no explanation. Held rows must come back, carrying the
return date the family needs, and the child summary must count them
separately rather than conflating them with the classes still running.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.parent import compose_parent
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-740"
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def _compose(db):
    return compose_parent(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
        academy_id=ACADEMY,
    )


async def _seed(db) -> None:
    await db["students"].insert_one(
        {
            "academy_id": ACADEMY,
            "student_id": "stu-1",
            "parent_id": "par-1",
            "full_name": "Alice Smith",
            "status": "active",
        }
    )
    await db["sessions"].insert_many(
        [
            {"academy_id": ACADEMY, "session_id": "sess-1", "title": "Morning Squad"},
            {"academy_id": ACADEMY, "session_id": "sess-2", "title": "Evening Squad"},
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "enrollment_id": "enr-active",
                "student_id": "stu-1",
                "session_id": "sess-1",
                "status": "active",
                "created_at": NOW,
            },
            {
                "academy_id": ACADEMY,
                "enrollment_id": "enr-held",
                "student_id": "stu-1",
                "session_id": "sess-2",
                "status": "held",
                "hold_return_on": "2026-10-15",
                "created_at": NOW,
            },
        ]
    )


@pytest.mark.asyncio
async def test_parent_enrollments_include_the_held_row_and_its_return_date(db) -> None:
    await _seed(db)
    parent = _compose(db)

    with tenant_scope(ACADEMY):
        rows = await parent.list_enrollments_for_parent("par-1")

    by_id = {row["enrollment_id"]: row for row in rows}
    assert set(by_id) == {"enr-active", "enr-held"}
    assert by_id["enr-held"]["status"] == "held"
    # Without the return date the badge can only say "on hold" — the family's
    # first question ("until when?") is exactly what makes them call the desk.
    assert by_id["enr-held"]["hold_return_on"] == "2026-10-15"
    assert by_id["enr-active"]["hold_return_on"] is None


@pytest.mark.asyncio
async def test_child_summary_counts_held_sessions_apart_from_active_ones(db) -> None:
    await _seed(db)
    parent = _compose(db)

    with tenant_scope(ACADEMY):
        [child] = await parent.list_children_for_parent("par-1")

    # Held is neither "still attending" nor "gone": counted, but on its own.
    assert child["active_session_count"] == 1
    assert child["held_session_count"] == 1
