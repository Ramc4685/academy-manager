"""Issue #706: Mongo repositories must hand back AWARE (UTC) datetimes.

The Motor client is built without ``tz_aware=True`` so every BSON datetime
comes back naive. Use cases compare those against ``datetime.now(UTC)`` and
blow up with ``TypeError: can't compare offset-naive and offset-aware
datetimes`` — the parent absence-notice 500 (Sentry COURTMASTR-FASTAPI-1).

These tests run over the mongomock ``db`` fixture, which returns NAIVE
datetimes on read exactly like real pymongo; in-memory fakes hold aware
values and can never reproduce the defect. Two layers:

* per-repository round-trips: save aware, read back, assert aware + same instant;
* the incident and its latent siblings, each wired to the REAL Mongo repo
  that was returning naive values, with the default (aware) clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import (
    AbsenceNotice,
    SubmitAbsenceNotice,
    SubmitAbsenceNoticeCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.cancel_session_occurrence import (
    CancelSessionOccurrence,
    CancelSessionOccurrenceCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.holds import SendHoldReminders
from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ApproveMakeupRequest,
    ApproveMakeupRequestCommand,
    SubmitMakeupRequest,
    SubmitMakeupRequestCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    ApproveTrialRequest,
    ApproveTrialRequestCommand,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import (
    MakeupRequest,
    MakeupWindowExpired,
    ParentSelfServicePolicy,
    TrialRequest,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_hold_repo import MongoHoldRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
    MongoMakeupRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.tests.application.test_absence_notices import (
    _FakeEnrollments as _AbsenceFakeEnrollments,
)
from backend.v2.tests.application.test_absence_notices import (
    _FakeNotices as _AbsenceFakeNotices,
)
from backend.v2.tests.application.test_absence_notices import (
    _FakePolicies as _AbsenceFakePolicies,
)
from backend.v2.tests.application.test_absence_notices import (
    _FakeStudents as _AbsenceFakeStudents,
)
from backend.v2.tests.application.test_cancel_session_occurrence import (
    FakeEnrollments as _CancelFakeEnrollments,
)
from backend.v2.tests.application.test_cancel_session_occurrence import (
    FakeSessions as _CancelFakeSessions,
)
from backend.v2.tests.application.test_cancel_session_occurrence import (
    _session as _cancel_session,
)
from backend.v2.tests.application.test_makeup_review import (
    _FakeEnrollments as _ReviewFakeEnrollments,
)
from backend.v2.tests.application.test_makeup_review import (
    _FakeOccurrenceRoster as _ReviewFakeRoster,
)
from backend.v2.tests.application.test_makeup_review import (
    _FakeSessions as _ReviewFakeSessions,
)
from backend.v2.tests.application.test_makeup_review import _session as _review_session
from backend.v2.tests.application.test_trial_requests import (
    _FakeEnrollments as _TrialFakeEnrollments,
)
from backend.v2.tests.application.test_trial_requests import (
    _FakeOccurrenceRoster as _TrialFakeRoster,
)
from backend.v2.tests.application.test_trial_requests import (
    _FakeSessions as _TrialFakeSessions,
)
from backend.v2.tests.application.test_trial_requests import _FakeTrials, _pending_trial
from backend.v2.tests.fixtures.enrollment_fakes import FakeHoldNotifier

pytestmark = pytest.mark.asyncio


def _aware_now() -> datetime:
    """A wall-clock 'now' rounded to whole seconds (BSON keeps milliseconds)."""
    return datetime.now(UTC).replace(microsecond=0)


def _occurrence(
    *,
    occurrence_id: str = "occ-706",
    session_id: str = "session-1",
    start_at: datetime,
    status: str = "scheduled",
    cancelled_at: datetime | None = None,
) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id="test-academy",
        session_id=session_id,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        scheduled_coach_id="coach-1",
        cancelled_at=cancelled_at,
    )


def _assert_aware_and_equal(actual: datetime | None, expected: datetime) -> None:
    assert actual is not None
    assert actual.tzinfo is not None, "repo handed back a naive datetime"
    assert actual == expected, "instant changed across the round-trip"


# --------------------------------------------------------------------------
# (a) per-repository round-trips
# --------------------------------------------------------------------------


async def test_occurrence_repo_reads_back_aware_datetimes(db, acad) -> None:
    repo = MongoSessionOccurrenceRepository(db)
    start = datetime(2026, 9, 9, 22, 45, tzinfo=UTC)
    cancelled = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    await repo.save_many(
        [
            _occurrence(occurrence_id="occ-a", start_at=start),
            _occurrence(
                occurrence_id="occ-b",
                start_at=start,
                status="cancelled",
                cancelled_at=cancelled,
            ),
        ]
    )

    scheduled = await repo.get("occ-a")
    assert scheduled is not None
    _assert_aware_and_equal(scheduled.start_at, start)
    _assert_aware_and_equal(scheduled.end_at, start + timedelta(hours=1))
    assert scheduled.cancelled_at is None

    cancelled_row = await repo.get("occ-b")
    assert cancelled_row is not None
    _assert_aware_and_equal(cancelled_row.cancelled_at, cancelled)

    next_start = await repo.next_upcoming_start_for_session(
        "session-1", now=start - timedelta(days=1)
    )
    _assert_aware_and_equal(next_start, start)


async def test_makeup_request_repo_reads_back_aware_datetimes(db, acad) -> None:
    repo = MongoMakeupRequestRepository(db)
    created = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    expires = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    decided = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)
    await repo.add(
        MakeupRequest(
            request_id="mk-1",
            academy_id=acad,
            student_id="student-1",
            parent_id="parent-1",
            missed_occurrence_id="occ-missed",
            status="approved",
            expires_at=expires,
            decided_by="admin-1",
            decided_at=decided,
            created_at=created,
        )
    )

    row = await repo.get("mk-1")
    assert row is not None
    _assert_aware_and_equal(row.expires_at, expires)
    _assert_aware_and_equal(row.created_at, created)
    _assert_aware_and_equal(row.decided_at, decided)


async def test_enrollment_writer_reads_back_aware_datetimes(db, acad) -> None:
    repo = MongoEnrollmentWriter(db)
    cancelled = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
    pending_at = datetime(2026, 9, 30, 23, 59, tzinfo=UTC)
    requested_at = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
    await repo.create(
        Enrollment(
            enrollment_id="enr-dates",
            academy_id=acad,
            session_id="session-1",
            student_id="student-1",
            status="active",
            cancelled_at=cancelled,
            pending_cancellation_at=pending_at,
            pending_cancellation_requested_at=requested_at,
        )
    )

    row = await repo.get("enr-dates")
    assert row is not None
    _assert_aware_and_equal(row.cancelled_at, cancelled)
    _assert_aware_and_equal(row.pending_cancellation_at, pending_at)
    _assert_aware_and_equal(row.pending_cancellation_requested_at, requested_at)
    assert row.hold_started_at is None
    assert row.hold_expires_at is None


async def test_enrollment_writer_hold_fields_read_back_aware(db, acad) -> None:
    repo = MongoEnrollmentWriter(db)
    await repo.create(
        Enrollment(
            enrollment_id="enr-held",
            academy_id=acad,
            session_id="session-1",
            student_id="student-1",
            status="active",
        )
    )
    started = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    expires = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
    await repo.mark_held_if_active(
        "enr-held",
        started_at=started,
        return_on=date(2026, 9, 15),
        expires_at=expires,
        reason="travel",
    )

    row = await repo.get("enr-held")
    assert row is not None
    assert row.status == "held"
    _assert_aware_and_equal(row.hold_started_at, started)
    _assert_aware_and_equal(row.hold_expires_at, expires)

    # MongoHoldRepository delegates to the same _to_domain.
    due = await MongoHoldRepository(db).list_due_for_reminder()
    assert [e.enrollment_id for e in due] == ["enr-held"]
    _assert_aware_and_equal(due[0].hold_started_at, started)
    _assert_aware_and_equal(due[0].hold_expires_at, expires)


async def test_trial_request_repo_reads_back_aware_datetimes(db, acad) -> None:
    repo = MongoTrialRequestRepository(db)
    created = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    decided = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)
    await repo.add(
        TrialRequest(
            request_id="tr-1",
            academy_id=acad,
            parent_user_id="parent-1",
            student_ref="existing_student",
            student_id="student-1",
            requested_session_id="session-1",
            preferred_start="2026-09-15",
            preferred_end="2026-09-22",
            status="approved",
            decided_by="admin-1",
            decided_at=decided,
            created_at=created,
        )
    )

    row = await repo.get("tr-1")
    assert row is not None
    _assert_aware_and_equal(row.created_at, created)
    _assert_aware_and_equal(row.decided_at, decided)


async def test_absence_notice_repo_reads_back_aware_datetimes(db, acad) -> None:
    repo = MongoAbsenceNoticeRepository(db)
    submitted = datetime(2026, 9, 9, 21, 30, 45, tzinfo=UTC)
    await repo.add(
        AbsenceNotice(
            notice_id="an-1",
            academy_id=acad,
            student_id="student-1",
            occurrence_id="occ-1",
            session_id="session-1",
            submitted_by="parent-1",
            submitted_at=submitted,
            notice_window_met=True,
        )
    )

    row = await repo.get_for_occurrence_and_student("occ-1", "student-1")
    assert row is not None
    _assert_aware_and_equal(row.submitted_at, submitted)


# --------------------------------------------------------------------------
# (b) the incident: SubmitAbsenceNotice over the REAL occurrence repo
# --------------------------------------------------------------------------


async def test_submit_absence_notice_over_real_occurrence_repo(db, acad) -> None:
    occurrences = MongoSessionOccurrenceRepository(db)
    start = _aware_now() + timedelta(days=1)
    await occurrences.save_many([_occurrence(start_at=start)])

    use_case = SubmitAbsenceNotice(
        students=_AbsenceFakeStudents(),
        occurrences=occurrences,
        enrollments=_AbsenceFakeEnrollments(),
        notices=_AbsenceFakeNotices(),
        policies=_AbsenceFakePolicies(),
        # default clock: datetime.now(UTC) — the aware side of the TypeError
    )

    notice = await use_case.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-706"
        )
    )

    assert isinstance(notice, AbsenceNotice)
    assert notice.occurrence_id == "occ-706"
    assert notice.notice_window_met is True


# --------------------------------------------------------------------------
# (c) latent siblings
# --------------------------------------------------------------------------


@dataclass
class _NoticeWithWindowMet:
    notice_window_met: bool = True


@dataclass
class _FakeNoticeQuery:
    async def get_for_occurrence_and_student(self, occurrence_id: str, student_id: str):
        return _NoticeWithWindowMet()


@dataclass
class _FakePolicies:
    policy: ParentSelfServicePolicy = field(
        default_factory=lambda: ParentSelfServicePolicy.default("test-academy")
    )

    async def get_or_default(self) -> ParentSelfServicePolicy:
        return self.policy


async def test_submit_makeup_request_over_real_occurrence_repo(db, acad) -> None:
    occurrences = MongoSessionOccurrenceRepository(db)
    missed_start = _aware_now() - timedelta(days=2)
    await occurrences.save_many(
        [_occurrence(occurrence_id="occ-missed", start_at=missed_start, status="completed")]
    )
    makeups = MongoMakeupRequestRepository(db)

    use_case = SubmitMakeupRequest(
        students=_AbsenceFakeStudents(),
        occurrences=occurrences,
        enrollments=_AbsenceFakeEnrollments(),
        notices=_FakeNoticeQuery(),
        makeups=makeups,
        policies=_FakePolicies(),
    )

    request = await use_case.execute(
        SubmitMakeupRequestCommand(
            parent_id="parent-1", student_id="student-1", missed_occurrence_id="occ-missed"
        )
    )

    assert request.status == "pending"
    assert request.expires_at == missed_start + timedelta(days=30)
    stored = await makeups.get(request.request_id)
    assert stored is not None
    _assert_aware_and_equal(stored.expires_at, request.expires_at)


async def test_approve_trial_request_over_real_occurrence_repo(db, acad) -> None:
    occurrences = MongoSessionOccurrenceRepository(db)
    start = _aware_now() + timedelta(days=2)
    await occurrences.save_many([_occurrence(occurrence_id="occ-trial", start_at=start)])
    trials = _FakeTrials()
    trials.added = [_pending_trial()]
    roster = _TrialFakeRoster()

    use_case = ApproveTrialRequest(
        trials=trials,
        occurrences=occurrences,
        enrollments=_TrialFakeEnrollments(),
        sessions=_TrialFakeSessions(),
        occurrence_roster=roster,
    )

    updated = await use_case.execute(
        ApproveTrialRequestCommand(
            request_id="req-1", actor_id="admin-1", occurrence_id="occ-trial"
        )
    )

    assert updated.status == "approved"
    assert updated.assigned_occurrence_id == "occ-trial"
    assert [e.student_id for e in roster.added] == ["student-1"]


async def test_cancel_session_occurrence_over_real_occurrence_repo(db, acad) -> None:
    occurrences = MongoSessionOccurrenceRepository(db)
    start = _aware_now() + timedelta(days=3)
    await occurrences.save_many(
        [_occurrence(occurrence_id="occ-cancel", session_id="sess-1", start_at=start)]
    )

    use_case = CancelSessionOccurrence(
        occurrences=occurrences,
        sessions=_CancelFakeSessions({"sess-1": _cancel_session()}),
        enrollments=_CancelFakeEnrollments(),
    )

    result = await use_case.execute(
        CancelSessionOccurrenceCommand(
            occurrence_id="occ-cancel", reason="Court flooded", actor_id="admin-1", notify=False
        )
    )

    assert result.occurrence.status == "cancelled"
    assert result.occurrence.cancelled_at is not None
    assert result.occurrence.cancelled_at.tzinfo is not None
    _assert_aware_and_equal(result.occurrence.start_at, start)


def _pending_makeup(*, expires_at: datetime, created_at: datetime) -> MakeupRequest:
    return MakeupRequest(
        request_id="mk-706",
        academy_id="test-academy",
        student_id="student-1",
        parent_id="parent-1",
        missed_occurrence_id="occ-missed",
        status="pending",
        expires_at=expires_at,
        created_at=created_at,
    )


async def test_approve_makeup_request_expired_window_over_real_makeup_repo(db, acad) -> None:
    """The expiry check ``now > request.expires_at`` is the first comparison
    ApproveMakeupRequest makes; a lapsed window must surface as
    MakeupWindowExpired, never as a TypeError 500."""
    makeups = MongoMakeupRequestRepository(db)
    now = _aware_now()
    await makeups.add(
        _pending_makeup(expires_at=now - timedelta(days=1), created_at=now - timedelta(days=31))
    )

    use_case = ApproveMakeupRequest(
        makeups=makeups,
        occurrences=MongoSessionOccurrenceRepository(db),
        enrollments=_ReviewFakeEnrollments(),
        sessions=_ReviewFakeSessions(),
        occurrence_roster=_ReviewFakeRoster(),
    )

    with pytest.raises(MakeupWindowExpired):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="mk-706", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


async def test_approve_makeup_request_open_window_over_real_repos(db, acad) -> None:
    makeups = MongoMakeupRequestRepository(db)
    occurrences = MongoSessionOccurrenceRepository(db)
    now = _aware_now()
    await makeups.add(
        _pending_makeup(expires_at=now + timedelta(days=20), created_at=now - timedelta(days=10))
    )
    await occurrences.save_many(
        [
            _occurrence(
                occurrence_id="occ-missed",
                session_id="session-missed",
                start_at=now - timedelta(days=10),
                status="completed",
            ),
            _occurrence(
                occurrence_id="occ-target",
                session_id="session-target",
                start_at=now + timedelta(days=5),
            ),
        ]
    )
    enrollments = _ReviewFakeEnrollments(
        [
            Enrollment(
                enrollment_id="enr-missed",
                academy_id=acad,
                session_id="session-missed",
                student_id="student-1",
                status="active",
            )
        ]
    )
    roster = _ReviewFakeRoster()

    use_case = ApproveMakeupRequest(
        makeups=makeups,
        occurrences=occurrences,
        enrollments=enrollments,
        sessions=_ReviewFakeSessions([_review_session("session-target")]),
        occurrence_roster=roster,
    )

    updated = await use_case.execute(
        ApproveMakeupRequestCommand(
            request_id="mk-706", actor_id="admin-1", target_occurrence_id="occ-target"
        )
    )

    assert updated.status == "approved"
    assert updated.approved_target_occurrence_id == "occ-target"
    assert updated.decided_at is not None and updated.decided_at.tzinfo is not None
    assert [e.occurrence_id for e in roster.entries] == ["occ-target"]


async def test_send_hold_reminders_over_real_enrollment_writer(db, acad) -> None:
    """The 5-minute scheduler job: a held row read back naive would raise on
    ``now - row.hold_started_at`` on every tick."""
    writer = MongoEnrollmentWriter(db)
    await writer.create(
        Enrollment(
            enrollment_id="enr-held",
            academy_id=acad,
            session_id="session-1",
            student_id="student-1",
            status="active",
        )
    )
    now = _aware_now()
    started = now - timedelta(days=31)
    await writer.mark_held_if_active(
        "enr-held",
        started_at=started,
        return_on=(now + timedelta(days=20)).date(),
        expires_at=started + timedelta(days=60),
        reason="travel",
    )
    notifier = FakeHoldNotifier()

    sent = await SendHoldReminders(holds=MongoHoldRepository(db), notifier=notifier).execute()

    assert sent == 1
    call: dict[str, Any] = notifier.reminder_calls[0]
    assert call["enrollment_id"] == "enr-held"
    assert call["notice_index"] == 1
    _assert_aware_and_equal(call["hold_started_at"], started)
