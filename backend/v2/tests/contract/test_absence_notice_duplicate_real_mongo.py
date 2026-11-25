"""The absence-notice duplicate guard holds on a real mongod.

The parent UI now disables dates that already carry a notice (the child
schedule's ``absence_reported`` flag), but that is a convenience: two tabs, or
two parents, can still submit the same date at once. The unique
(academy_id, occurrence_id, student_id) index must reject the loser, and the
repo must surface it as ``DuplicateAbsenceNotice`` (a 409), not a 500.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.domain.self_service import DuplicateAbsenceNotice
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
)


def _notice(notice_id: str, *, student_id: str = "student-alex") -> AbsenceNotice:
    return AbsenceNotice(
        notice_id=notice_id,
        academy_id="test-academy",
        student_id=student_id,
        occurrence_id="occ-nov-28",
        session_id="session-1",
        submitted_by="parent-1",
        submitted_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        notice_window_met=True,
    )


async def test_concurrent_duplicate_notices_keep_exactly_one(real_db, acad) -> None:
    repo = MongoAbsenceNoticeRepository(real_db)

    results = await asyncio.gather(
        repo.add(_notice("an-tab-1")),
        repo.add(_notice("an-tab-2")),
        return_exceptions=True,
    )

    assert sum(r is None for r in results) == 1
    assert sum(isinstance(r, DuplicateAbsenceNotice) for r in results) == 1
    stored = await repo.list_for_student("student-alex")
    assert [n.occurrence_id for n in stored] == ["occ-nov-28"]


async def test_sibling_can_report_the_same_date(real_db, acad) -> None:
    repo = MongoAbsenceNoticeRepository(real_db)
    await repo.add(_notice("an-alex"))
    await repo.add(_notice("an-sam", student_id="student-sam"))

    with pytest.raises(DuplicateAbsenceNotice):
        await repo.add(_notice("an-alex-again"))
