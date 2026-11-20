"""#1037 / #1041: the parent makeup picker lists what the server would accept.

``ListMakeupCandidates`` runs the same ``MakeupEligibility`` check as
``SubmitMakeupRequest`` for every past class of every child, so siblings in
one class are separate candidates, a denied request is re-requestable while
the window is open, and a no-notice class appears when the academy allows it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ListMakeupCandidates,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.enrollment.domain.self_service import (
    MakeupRequest,
    ParentSelfServicePolicy,
)
from backend.v2.tests.application.test_makeup_requests import (
    _absence_notice,
    _enrollment,
    _FakeMakeups,
    _FakeNotices,
    _FakePolicies,
    _now,
    _occurrence,
    _student,
)

NOW = _now()  # 2026-07-10 08:00 UTC


class _Students:
    def __init__(self, students):
        self._students = students

    async def list_for_parent(self, parent_id):
        return [s for s in self._students if s.parent_id == parent_id]


class _Enrollments:
    def __init__(self, enrollments):
        self._rows = enrollments

    async def active_or_paused_for_student(self, student_id):
        return [
            e for e in self._rows if e.student_id == student_id and e.status in {"active", "paused"}
        ]

    async def is_active_or_paused(self, session_id, student_id):
        return any(
            e.session_id == session_id and e.student_id == student_id
            for e in await self.active_or_paused_for_student(student_id)
        )


class _Occurrences:
    def __init__(self, occurrences):
        self._rows = occurrences
        self.windows = []

    async def list_for_session_between(self, *, session_id, start_at, end_at):
        self.windows.append((session_id, start_at, end_at))
        return [
            o for o in self._rows if o.session_id == session_id and start_at <= o.start_at <= end_at
        ]


class _Sessions:
    async def get_many(self, session_ids):
        return [
            Session(
                session_id=sid,
                academy_id="acad",
                coach_id="c",
                title=f"Class {sid}",
                location="Court",
                start_at=NOW,
                end_at=NOW,
                capacity=10,
            )
            for sid in session_ids
        ]


def _use_case(*, students, enrollments, occurrences, notices=None, makeups=None, policy=None):
    return ListMakeupCandidates(
        students=_Students(students),
        enrollments=_Enrollments(enrollments),
        occurrences=_Occurrences(occurrences),
        sessions=_Sessions(),
        notices=notices or _FakeNotices(),
        makeups=makeups or _FakeMakeups(),
        policies=_FakePolicies(policy),
        clock=_now,
    )


def _missed(occurrence_id="occ-missed", days_ago=2, **kw):
    return _occurrence(occurrence_id=occurrence_id, start_at=NOW - timedelta(days=days_ago), **kw)


SIBLINGS = [_student("kid-a"), _student("kid-b")]


@pytest.mark.asyncio
async def test_siblings_in_the_same_class_are_separate_candidates() -> None:
    rows = await _use_case(
        students=SIBLINGS,
        enrollments=[_enrollment(student_id="kid-a"), _enrollment(student_id="kid-b")],
        occurrences=[_missed()],
        notices=_FakeNotices(
            [
                _absence_notice(student_id="kid-a"),
                _absence_notice(student_id="kid-b").model_copy(update={"notice_id": "n-2"}),
            ]
        ),
    ).execute("parent-1")

    assert [(r.student_id, r.occurrence_id) for r in rows] == [
        ("kid-a", "occ-missed"),
        ("kid-b", "occ-missed"),
    ]
    assert rows[0].class_title == "Class session-1"
    assert rows[0].has_notice is True


@pytest.mark.asyncio
async def test_one_childs_request_does_not_hide_the_siblings_absence() -> None:
    makeups = _FakeMakeups()
    await makeups.add(_request("kid-a", status="pending"))

    rows = await _use_case(
        students=SIBLINGS,
        enrollments=[_enrollment(student_id="kid-a"), _enrollment(student_id="kid-b")],
        occurrences=[_missed()],
        makeups=makeups,
        policy=_policy(requires_notice=False),
    ).execute("parent-1")

    assert [r.student_id for r in rows] == ["kid-b"]


@pytest.mark.asyncio
async def test_a_denied_request_is_re_requestable_inside_the_window() -> None:
    makeups = _FakeMakeups()
    await makeups.add(_request("kid-a", status="denied"))

    rows = await _use_case(
        students=[_student("kid-a")],
        enrollments=[_enrollment(student_id="kid-a")],
        occurrences=[_missed()],
        makeups=makeups,
        policy=_policy(requires_notice=False),
    ).execute("parent-1")

    assert [r.student_id for r in rows] == ["kid-a"]


@pytest.mark.asyncio
async def test_notice_policy_decides_whether_a_no_notice_class_is_listed() -> None:
    kwargs = dict(
        students=[_student()],
        enrollments=[_enrollment()],
        occurrences=[_missed("occ-noticed", 2), _missed("occ-late", 3), _missed("occ-none", 4)],
        notices=_FakeNotices(
            [
                _absence_notice(occurrence_id="occ-noticed"),
                _absence_notice(occurrence_id="occ-late", window_met=False),
            ]
        ),
    )
    required = await _use_case(**kwargs, policy=_policy(requires_notice=True)).execute("parent-1")
    optional = await _use_case(**kwargs, policy=_policy(requires_notice=False)).execute("parent-1")

    assert [r.occurrence_id for r in required] == ["occ-noticed"]
    assert [(r.occurrence_id, r.has_notice) for r in optional] == [
        ("occ-noticed", True),
        ("occ-late", True),
        ("occ-none", False),
    ]


@pytest.mark.asyncio
async def test_future_expired_cancelled_and_unenrolled_classes_are_not_listed() -> None:
    rows = await _use_case(
        students=[_student()],
        enrollments=[_enrollment(), _enrollment(session_id="dropped", status="dropped")],
        occurrences=[
            _missed("occ-ok", 2),
            _missed("occ-future", -1),
            _missed("occ-old", 31),
            _missed("occ-cancelled", 3, status="cancelled"),
            _missed("occ-dropped", 2, session_id="dropped"),
        ],
        policy=_policy(requires_notice=False),
    ).execute("parent-1")

    assert [r.occurrence_id for r in rows] == ["occ-ok"]
    assert rows[0].expires_at == NOW - timedelta(days=2) + timedelta(days=30)


@pytest.mark.asyncio
async def test_another_parents_children_are_never_read() -> None:
    rows = await _use_case(
        students=[_student("theirs", parent_id="parent-2")],
        enrollments=[_enrollment(student_id="theirs")],
        occurrences=[_missed()],
        policy=_policy(requires_notice=False),
    ).execute("parent-1")
    assert rows == []


@pytest.mark.asyncio
async def test_makeups_turned_off_lists_nothing() -> None:
    policy = _policy(requires_notice=False).model_copy(update={"can_request_makeup": False})
    rows = await _use_case(
        students=[_student()], enrollments=[_enrollment()], occurrences=[_missed()], policy=policy
    ).execute("parent-1")
    assert rows == []


def _policy(*, requires_notice: bool) -> ParentSelfServicePolicy:
    return ParentSelfServicePolicy.default("acad").model_copy(
        update={"makeup_requires_notice": requires_notice}
    )


def _request(student_id: str, *, status: str) -> MakeupRequest:
    return MakeupRequest(
        request_id=f"req-{student_id}-{status}",
        academy_id="acad",
        student_id=student_id,
        parent_id="parent-1",
        missed_occurrence_id="occ-missed",
        status=status,  # type: ignore[arg-type]
        expires_at=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=NOW,
    )
