"""``recorded_by_admin`` round-trips through the real absence-notice repo (#616).

Runs over the mongomock ``db`` fixture so the read path is the real
``_to_domain``: notices written before the field existed must read back as
parent submissions (``False``), and an admin-recorded notice must keep the flag.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
)


def _notice(*, notice_id: str, occurrence_id: str, recorded_by_admin: bool) -> AbsenceNotice:
    return AbsenceNotice(
        notice_id=notice_id,
        academy_id="test-academy",
        student_id="student-1",
        occurrence_id=occurrence_id,
        session_id="session-1",
        submitted_by="admin-1" if recorded_by_admin else "parent-1",
        submitted_at=datetime(2026, 9, 9, 21, 30, 45, tzinfo=UTC),
        notice_window_met=True,
        recorded_by_admin=recorded_by_admin,
    )


async def test_admin_recorded_flag_round_trips(db, acad) -> None:
    repo = MongoAbsenceNoticeRepository(db)
    await repo.add(_notice(notice_id="an-admin", occurrence_id="occ-1", recorded_by_admin=True))
    await repo.add(_notice(notice_id="an-parent", occurrence_id="occ-2", recorded_by_admin=False))

    by_occurrence = {n.occurrence_id: n for n in await repo.list_all()}
    assert by_occurrence["occ-1"].recorded_by_admin is True
    assert by_occurrence["occ-2"].recorded_by_admin is False


async def test_legacy_document_without_flag_reads_as_parent_submission(db, acad) -> None:
    # Documents written before this field existed carry no key at all.
    await db["absence_notices"].insert_one(
        {
            "notice_id": "an-legacy",
            "academy_id": acad,
            "student_id": "student-1",
            "occurrence_id": "occ-legacy",
            "session_id": "session-1",
            "submitted_by": "parent-1",
            "submitted_at": datetime(2026, 9, 1, 12, 0, 0),
            "notice_window_met": False,
        }
    )
    repo = MongoAbsenceNoticeRepository(db)

    row = await repo.get_for_occurrence_and_student("occ-legacy", "student-1")

    assert row is not None
    assert row.recorded_by_admin is False
