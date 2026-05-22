from __future__ import annotations

import datetime

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    MarkAttendance,
    MarkAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import StudentNotEnrolled


def test_occurrence_details_has_template_session_id():
    od = OccurrenceDetails(
        occurrence_id="occ-jun4",
        session_id="sess-jun4",
        starts_at=datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.UTC),
        status="scheduled",
        scheduled_coach_id="coach1",
        template_session_id="sess-may28",
    )
    assert od.template_session_id == "sess-may28"


def test_occurrence_details_template_session_id_optional():
    od = OccurrenceDetails(
        occurrence_id="occ1",
        session_id="sess1",
        starts_at=datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.UTC),
        status="scheduled",
        scheduled_coach_id="coach1",
    )
    assert od.template_session_id is None


# ---------------------------------------------------------------------------
# Behavioral tests for the mark_attendance template_session_id fallback
# ---------------------------------------------------------------------------

_NOW = datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.UTC)


class _FakeAttendanceRepo:
    def __init__(self):
        self.saved = []

    async def save(self, att):
        self.saved.append(att)

    async def find_existing(self, occurrence_id, student_id):
        return None

    async def find_by_attendance_id(self, aid):
        return None


class _FakeOccurrenceWithTemplate:
    """Returns an occurrence whose session_id differs from the template."""

    def __init__(self, template_session_id):
        self._tmpl = template_session_id

    async def get(self, occurrence_id):
        return OccurrenceDetails(
            occurrence_id=occurrence_id,
            session_id="sess-jun4",
            starts_at=_NOW,
            status="scheduled",
            scheduled_coach_id="coach1",
            template_session_id=self._tmpl,
        )


class _FakeEnrollmentBySession:
    """Enrolled only in the template session, not the occurrence session."""

    def __init__(self, enrolled_in: str):
        self._enrolled_in = enrolled_in

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return session_id == self._enrolled_in


class _FakeOutbox:
    def __init__(self):
        self.appended = []

    async def append(self, event, *, session=None):
        self.appended.append(event)

    async def pull_unprocessed(self, limit=100):
        return []

    async def mark_processed(self, event_id):
        pass


class _FakeIdempotency:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def put(self, key, value):
        self._store[key] = value


def _make_uc(occurrence_lookup, enrollment_lookup):
    return MarkAttendance(
        attendance_repo=_FakeAttendanceRepo(),
        occurrence_lookup=occurrence_lookup,
        enrollment_lookup=enrollment_lookup,
        outbox=_FakeOutbox(),
        idempotency_store=_FakeIdempotency(),
        academy_id="test-academy",
        clock=lambda: _NOW,
    )


async def test_enrollment_via_template_session_id_succeeds():
    """Student enrolled in template session can mark attendance on recurred occurrence."""
    uc = _make_uc(
        occurrence_lookup=_FakeOccurrenceWithTemplate("sess-may28"),
        enrollment_lookup=_FakeEnrollmentBySession("sess-may28"),
    )
    cmd = MarkAttendanceCommand(
        mutation_id="m1",
        occurrence_id="occ-jun4",
        session_id="sess-jun4",
        student_id="st1",
        status="present",  # type: ignore[arg-type]
    )
    result = await uc.execute(cmd, coach_id="coach1")
    assert result.student_id == "st1"


async def test_enrollment_missing_raises_not_enrolled():
    """Student not enrolled in either session raises StudentNotEnrolled."""
    uc = _make_uc(
        occurrence_lookup=_FakeOccurrenceWithTemplate("sess-may28"),
        enrollment_lookup=_FakeEnrollmentBySession("some-other-session"),
    )
    cmd = MarkAttendanceCommand(
        mutation_id="m2",
        occurrence_id="occ-jun4",
        session_id="sess-jun4",
        student_id="st1",
        status="present",  # type: ignore[arg-type]
    )
    try:
        await uc.execute(cmd, coach_id="coach1")
        raise AssertionError("Expected StudentNotEnrolled")
    except StudentNotEnrolled:
        pass


async def test_null_template_session_id_still_raises_not_enrolled():
    """When template_session_id is None and primary check fails, StudentNotEnrolled is raised."""
    uc = _make_uc(
        occurrence_lookup=_FakeOccurrenceWithTemplate(None),
        enrollment_lookup=_FakeEnrollmentBySession("some-other-session"),
    )
    cmd = MarkAttendanceCommand(
        mutation_id="m3",
        occurrence_id="occ-jun4",
        session_id="sess-jun4",
        student_id="st1",
        status="present",  # type: ignore[arg-type]
    )
    try:
        await uc.execute(cmd, coach_id="coach1")
        raise AssertionError("Expected StudentNotEnrolled")
    except StudentNotEnrolled:
        pass
