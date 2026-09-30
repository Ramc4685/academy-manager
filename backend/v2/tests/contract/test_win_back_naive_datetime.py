"""Win-back daily job over the REAL enrollment-event repo (prod 2026-09-30).

``send_win_back_notices`` failed for BLNO on every attempt with
``TypeError: can't subtract offset-naive and offset-aware datetimes``.
``MongoEnrollmentEventRepository._to_domain`` handed back the BSON
``effective_at`` / ``occurred_at`` NAIVE (Motor runs without
``tz_aware=True``) and ``SendWinBackNotices._process_event`` computes
``now - event.effective_at`` against an aware ``datetime.now(UTC)``. Same
class as #706; the in-memory fakes in ``test_win_back_notices.py`` hold
aware values and could never reproduce it.

Every test runs twice: over the mongomock ``db`` (returns naive datetimes on
read, like pymongo) and over ``real_db`` (a real ``mongod``; skipped when
none is reachable).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.win_back_send_repo import MongoWinBackSendRepository
from backend.v2.contexts.enrollment.application.use_cases.win_back import SendWinBackNotices
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
    MongoEnrollmentEventRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.tests.application.test_win_back_notices import (
    FakeEnrollmentQuery,
    FakeFamilyBalanceLookup,
    FakeStudentQuery,
    FakeWinBackNotifier,
    _student,
)

pytestmark = pytest.mark.asyncio

ACADEMY_ID = "acad-win-back-naive"


@pytest.fixture(params=["mongomock", "real_mongod"])
def any_db(request: pytest.FixtureRequest) -> Any:
    name = "db" if request.param == "mongomock" else "real_db"
    return request.getfixturevalue(name)


def _now() -> datetime:
    # Whole seconds: BSON keeps milliseconds only.
    return datetime.now(UTC).replace(microsecond=0)


def _dropped(student_id: str, *, at: datetime) -> EnrollmentLifecycleEvent:
    return EnrollmentLifecycleEvent(
        event_id=f"evt-{student_id}",
        academy_id=ACADEMY_ID,
        event_type="dropped",
        enrollment_id=f"enr-{student_id}",
        student_id=student_id,
        effective_at=at,
        occurred_at=at,
    )


def _use_case(
    db: Any, *, students: list[str], now: datetime | None = None
) -> tuple[SendWinBackNotices, FakeWinBackNotifier]:
    notifier = FakeWinBackNotifier()
    kwargs: dict[str, Any] = {}
    if now is not None:
        kwargs["clock"] = lambda: now
    use_case = SendWinBackNotices(
        enrollment_events=MongoEnrollmentEventRepository(db),
        enrollments=FakeEnrollmentQuery(),
        students=FakeStudentQuery([_student(s) for s in students]),
        send_repo=MongoWinBackSendRepository(db),
        balance_lookup=FakeFamilyBalanceLookup(),
        notifier=notifier,
        **kwargs,
    )
    return use_case, notifier


async def test_event_repo_reads_back_aware_datetimes(any_db: Any) -> None:
    at = _now() - timedelta(days=31)
    with tenant_scope(ACADEMY_ID):
        repo = MongoEnrollmentEventRepository(any_db)
        await repo.record(_dropped("stu-1", at=at))

        in_range = await repo.list_in_range(
            start=at - timedelta(days=1),
            end=at + timedelta(days=1),
            event_types=frozenset({"dropped"}),
        )
        by_enrollment = await repo.list_for_enrollment("enr-stu-1")

    for events in (in_range, by_enrollment):
        assert len(events) == 1
        event = events[0]
        assert event.effective_at.tzinfo is not None, "repo handed back a naive effective_at"
        assert event.occurred_at.tzinfo is not None, "repo handed back a naive occurred_at"
        assert event.effective_at == at
        assert event.occurred_at == at


async def test_daily_job_with_default_aware_clock_sends_the_due_milestone(any_db: Any) -> None:
    """The production incident: default ``datetime.now(UTC)`` clock, a real
    dropped event read back from Mongo. Raised TypeError before the fix."""
    with tenant_scope(ACADEMY_ID):
        await MongoEnrollmentEventRepository(any_db).record(
            _dropped("stu-1", at=_now() - timedelta(days=31))
        )
        use_case, notifier = _use_case(any_db, students=["stu-1"])

        sent = await use_case.execute(academy_id=ACADEMY_ID)

    assert sent == 1
    assert [(n["student_id"], n["milestone_days"]) for n in notifier.sent] == [("stu-1", 30)]
    assert notifier.sent[0]["dropped_at"].tzinfo is not None


async def test_retried_tick_does_not_resend_a_milestone_already_sent(any_db: Any) -> None:
    """The scheduler retries a failed job and the next day's tick re-reads
    the same dropped event: the claim row must still block a re-send."""
    now = _now()
    with tenant_scope(ACADEMY_ID):
        await MongoEnrollmentEventRepository(any_db).record(
            _dropped("stu-1", at=now - timedelta(days=30, hours=1))
        )
        first, first_notifier = _use_case(any_db, students=["stu-1"], now=now)
        assert await first.execute(academy_id=ACADEMY_ID) == 1

        retry, retry_notifier = _use_case(any_db, students=["stu-1"], now=now)
        assert await retry.execute(academy_id=ACADEMY_ID) == 0

        next_day, next_day_notifier = _use_case(
            any_db, students=["stu-1"], now=now + timedelta(days=1)
        )
        assert await next_day.execute(academy_id=ACADEMY_ID) == 0

    assert len(first_notifier.sent) == 1
    assert retry_notifier.sent == []
    assert next_day_notifier.sent == []
    rows = await any_db["win_back_notice_sends"].count_documents(
        {"academy_id": ACADEMY_ID, "student_id": "stu-1"}
    )
    assert rows == 1


async def test_a_missed_day_is_picked_up_on_the_next_tick(any_db: Any) -> None:
    """Deploy-note semantics: a milestone that fell due on a day the job
    failed is sent on the next successful tick (the 30-day notice stays due
    until the 60-day one supersedes it)."""
    now = _now()
    with tenant_scope(ACADEMY_ID):
        await MongoEnrollmentEventRepository(any_db).record(
            _dropped("stu-1", at=now - timedelta(days=31))
        )
        use_case, notifier = _use_case(any_db, students=["stu-1"], now=now)
        assert await use_case.execute(academy_id=ACADEMY_ID) == 1

    assert [n["milestone_days"] for n in notifier.sent] == [30]
