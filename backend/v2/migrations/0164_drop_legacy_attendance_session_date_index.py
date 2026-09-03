"""Drop the v1 ``attendance`` unique index on (session_id, student_id, date).

Production incident 2026-09-03 (#638): coaches could mark *some* students and
not others. The legacy v1 schema had a unique index
``session_id_1_student_id_1_date_1``. v2 attendance rows are keyed by
``occurrence_id`` and never set ``date``, so under that index every v2 row for
a recurring session collapses to the single key ``(session_id, student_id,
null)`` — a student who has been marked once in a session can never be marked
again in it. Prod data confirmed it exactly: every student marked on the
2026-09-02 occurrence had zero earlier v2 rows for the session; the one
student with an earlier v2 row (2026-06-10) was the one the coach could not
mark. Left in place, every student marked this week would fail next week.

Integrity is already guaranteed by ``attendance_occurrence_unique``
(academy_id, occurrence_id, student_id) from migration 0081. The 8 remaining
v1-shaped rows (which do carry ``date``) are untouched.
"""

from __future__ import annotations

from contextlib import suppress

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0164_drop_legacy_attendance_session_date_index"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    with suppress(Exception):  # already gone on fresh databases
        await db["attendance"].drop_index("session_id_1_student_id_1_date_1")
