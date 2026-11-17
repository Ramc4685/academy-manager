"""Academy-wide closure over a real mongod (L12 front-desk tools).

``CloseAcademyDates`` is a loop over the fully wired ``CancelSessionOccurrence``
(billing sync, payout lock, lifecycle events). This drives the production
composition (``compose_occurrence_cancellations``) against the migrated
schema, so the occurrence CAS, the validators and the event writes are real.
Only the family notifier is a recorder: nothing here may send email.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import backend.v2.composition.admin as admin_composition
from backend.v2.composition.occurrence_cancellation import compose_occurrence_cancellations
from backend.v2.contexts.enrollment.application.ports import ClosureNotice
from backend.v2.contexts.enrollment.application.use_cases.close_academy_dates import (
    CloseAcademyDatesCommand,
)
from backend.v2.contexts.enrollment.domain.errors import ClosureRangeInvalid
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-closure"
NOW = datetime.now(UTC).replace(microsecond=0)
CLOSE_START = NOW + timedelta(days=5)
CLOSE_END = NOW + timedelta(days=9)


class RecordingClosureNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def academy_closed(self, *, dates, reason, actor_id) -> ClosureNotice:
        self.calls.append({"dates": list(dates), "reason": reason, "actor_id": actor_id})
        return ClosureNotice(families_affected=1, families_emailed=1)


async def _no_materialize(session: Any) -> None:
    return None


async def _seed(db: Any) -> None:
    await db["sessions"].insert_one(
        {
            "session_id": "sess-1",
            "academy_id": ACADEMY,
            "coach_id": "coach-1",
            "title": "Juniors",
            "location": "Court 1",
            "start_at": NOW + timedelta(days=1),
            "end_at": NOW + timedelta(days=1, hours=1),
            "capacity": 10,
            "status": "scheduled",
            "days_of_week": ["monday"],
            "start_time": "17:00",
            "end_time": "18:00",
        }
    )
    await db["enrollments"].insert_one(
        {
            "enrollment_id": "enr-1",
            "academy_id": ACADEMY,
            "session_id": "sess-1",
            "student_id": "stu-1",
            "parent_id": "par-1",
            "status": "active",
            "enrolled_at": NOW - timedelta(days=30),
            "created_at": NOW - timedelta(days=30),
        }
    )
    rows = [
        ("occ-before", NOW + timedelta(days=2), "scheduled"),
        ("occ-in-1", CLOSE_START + timedelta(hours=2), "scheduled"),
        ("occ-in-2", CLOSE_START + timedelta(days=2), "scheduled"),
        ("occ-in-done", CLOSE_START + timedelta(days=3), "cancelled"),
        ("occ-after", CLOSE_END + timedelta(days=1), "scheduled"),
    ]
    for occurrence_id, start, status in rows:
        await db["session_occurrences"].insert_one(
            {
                "occurrence_id": occurrence_id,
                "academy_id": ACADEMY,
                "session_id": "sess-1",
                "template_session_id": "sess-1",
                "start_at": start,
                "end_at": start + timedelta(hours=1),
                "status": status,
                "scheduled_coach_id": "coach-1",
                "is_billable": status == "scheduled",
                "is_payable": status == "scheduled",
            }
        )


def _command(**overrides: Any) -> CloseAcademyDatesCommand:
    values: dict[str, Any] = {
        "start_at": CLOSE_START,
        "end_at": CLOSE_END,
        "reason": "Thanksgiving",
        "actor_id": "admin-1",
    }
    values.update(overrides)
    return CloseAcademyDatesCommand(**values)


async def _statuses(db: Any) -> dict[str, str]:
    return {
        doc["occurrence_id"]: doc["status"]
        async for doc in db["session_occurrences"].find({"academy_id": ACADEMY})
    }


async def test_closure_cancels_only_the_range_and_notifies_once(real_db: Any) -> None:
    await _seed(real_db)
    notifier = RecordingClosureNotifier()
    with tenant_scope(ACADEMY):
        close = compose_occurrence_cancellations(real_db, notifier, _no_materialize)[
            "close_academy_dates"
        ]
        close._notifier = notifier

        preview = await close.execute(_command(dry_run=True))
        assert [d.occurrence_id for d in preview.dates] == ["occ-in-1", "occ-in-2"]
        assert {d.status for d in preview.dates} == {"would_cancel"}
        assert (await _statuses(real_db))["occ-in-1"] == "scheduled"
        assert notifier.calls == []

        result = await close.execute(_command())

    assert result.cancelled == 2 and result.skipped == 0
    assert await _statuses(real_db) == {
        "occ-before": "scheduled",
        "occ-in-1": "cancelled",
        "occ-in-2": "cancelled",
        "occ-in-done": "cancelled",
        "occ-after": "scheduled",
    }
    cancelled = await real_db["session_occurrences"].find_one({"occurrence_id": "occ-in-1"})
    assert cancelled["is_billable"] is False and cancelled["is_payable"] is False
    assert cancelled["cancellation_reason"] == "Thanksgiving"
    # One lifecycle event per enrolled student per date, as the single cancel writes.
    events = await real_db["enrollment_events"].count_documents(
        {"academy_id": ACADEMY, "event_type": "occurrence_cancelled", "enrollment_id": "enr-1"}
    )
    assert events == 2
    # ONE notifier call for the whole closure, carrying both dates.
    assert len(notifier.calls) == 1
    assert [d.start_at for d in notifier.calls[0]["dates"]] == sorted(
        d.start_at for d in notifier.calls[0]["dates"]
    )
    assert len(notifier.calls[0]["dates"]) == 2


async def test_rerunning_a_closure_cancels_nothing_and_emails_nobody(real_db: Any) -> None:
    await _seed(real_db)
    notifier = RecordingClosureNotifier()
    with tenant_scope(ACADEMY):
        close = compose_occurrence_cancellations(real_db, notifier, _no_materialize)[
            "close_academy_dates"
        ]
        close._notifier = notifier
        await close.execute(_command())
        again = await close.execute(_command())
    assert again.cancelled == 0 and again.dates == ()
    assert len(notifier.calls) == 1


async def test_closure_refuses_a_range_past_the_materialisation_window(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        close = compose_occurrence_cancellations(real_db, None, _no_materialize)[
            "close_academy_dates"
        ]
        with pytest.raises(ClosureRangeInvalid):
            await close.execute(_command(end_at=NOW + timedelta(days=61)))
        with pytest.raises(ClosureRangeInvalid):
            await close.execute(_command(start_at=CLOSE_END, end_at=CLOSE_START))


async def test_closure_materialises_live_recurring_sessions_first(real_db: Any) -> None:
    await _seed(real_db)
    await real_db["sessions"].insert_one(
        {
            "session_id": "sess-gone",
            "academy_id": ACADEMY,
            "coach_id": "coach-1",
            "title": "Old",
            "location": "Court 2",
            "start_at": NOW,
            "end_at": NOW + timedelta(hours=1),
            "capacity": 10,
            "status": "cancelled",
            "days_of_week": ["monday"],
            "start_time": "17:00",
            "end_time": "18:00",
        }
    )
    seen: list[str] = []

    async def materialize(session: Any) -> None:
        seen.append(session.session_id)

    with tenant_scope(ACADEMY):
        assert [s.session_id for s in await MongoSessionRepository(real_db).list_live()] == [
            "sess-1"
        ]
        close = compose_occurrence_cancellations(real_db, None, materialize)["close_academy_dates"]
        await close.execute(_command(dry_run=True))
    assert seen == ["sess-1"]


# --- Risk-review regressions (L12 fix round) ---------------------------------

# Monday 2026-01-05 21:00 UTC = 15:00 America/Chicago: AFTER the 09:00 class.
AFTERNOON = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
TEST_ACADEMY = "test-academy"


def _freeze_admin_clock(monkeypatch: Any, instant: datetime) -> None:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return instant.replace(tzinfo=None) if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(admin_composition, "datetime", _Frozen)


def _real_maintain(database: Any) -> Any:
    from backend.v2.composition.admin import compose_admin
    from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
    from backend.v2.shared.events import MongoOutbox
    from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore

    admin = compose_admin(
        database, MongoOutbox(database), MongoIdempotencyStore(database), FakeStripeGateway()
    )
    return admin.maintain_session_occurrences


async def _seed_weekly(database: Any, session_id: str, **extra: Any) -> None:
    await database["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": TEST_ACADEMY,
            "coach_id": "coach-1",
            "title": "Juniors",
            "location": "Court 1",
            "start_at": AFTERNOON - timedelta(days=60),
            "end_at": AFTERNOON - timedelta(days=60) + timedelta(hours=1),
            "capacity": 10,
            "status": "scheduled",
            "days_of_week": ["Mon"],
            "start_time": "09:00",
            "end_time": "10:00",
            "timezone": "America/Chicago",
            **extra,
        }
    )


def _frozen_closure(database: Any, notifier: Any, materialize: Any) -> Any:
    close = compose_occurrence_cancellations(database, notifier, materialize)["close_academy_dates"]
    close._now = lambda: AFTERNOON
    close._cancel._now = lambda: AFTERNOON
    return close


async def test_preview_never_rewrites_a_class_that_ran_this_morning(
    real_db: Any, acad: str, monkeypatch: Any
) -> None:
    """B1: materialising (any preview or closure) once skipped rows that had
    started today, so a class cancelled this morning came back as scheduled
    and a substitute this morning was wiped."""
    _freeze_admin_clock(monkeypatch, AFTERNOON)
    await _seed_weekly(real_db, "sess-1")
    await _seed_weekly(real_db, "sess-2")
    start = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)  # 09:00 Chicago today
    base = {
        "academy_id": TEST_ACADEMY,
        "start_at": start,
        "end_at": start + timedelta(hours=1),
        "scheduled_coach_id": "coach-1",
    }
    await real_db["session_occurrences"].insert_many(
        [
            {
                **base,
                "occurrence_id": "sess-1:2026-01-05:09:00",
                "session_id": "sess-1",
                "template_session_id": "sess-1",
                "status": "cancelled",
                "cancellation_reason": "Coach sick",
                "is_billable": False,
                "is_payable": False,
            },
            {
                **base,
                "occurrence_id": "sess-2:2026-01-05:09:00",
                "session_id": "sess-2",
                "template_session_id": "sess-2",
                "status": "scheduled",
                "actual_coach_id": "sub-coach",
                "substitute_coach_id": "sub-coach",
                "is_billable": True,
                "is_payable": True,
            },
        ]
    )
    close = _frozen_closure(real_db, RecordingClosureNotifier(), _real_maintain(real_db))
    await close.execute(
        CloseAcademyDatesCommand(
            start_at=AFTERNOON + timedelta(days=20),
            end_at=AFTERNOON + timedelta(days=22),
            reason="Thanksgiving",
            dry_run=True,
        )
    )
    cancelled = await real_db["session_occurrences"].find_one(
        {"occurrence_id": "sess-1:2026-01-05:09:00"}
    )
    covered = await real_db["session_occurrences"].find_one(
        {"occurrence_id": "sess-2:2026-01-05:09:00"}
    )
    assert cancelled["status"] == "cancelled" and cancelled["is_billable"] is False
    assert covered["actual_coach_id"] == "sub-coach"
    assert covered["substitute_coach_id"] == "sub-coach"


async def test_closure_skips_classes_outside_their_own_dates(
    real_db: Any, acad: str, monkeypatch: Any
) -> None:
    """F2: a weekly class that ended (or has not started) is not materialised,
    so the closure cancels nothing for it."""
    _freeze_admin_clock(monkeypatch, AFTERNOON)
    await _seed_weekly(real_db, "sess-ended", start_date="2025-09-01", end_date="2025-12-15")
    await _seed_weekly(real_db, "sess-future", start_date="2026-03-02", end_date="2026-05-25")
    notifier = RecordingClosureNotifier()
    close = _frozen_closure(real_db, notifier, _real_maintain(real_db))
    result = await close.execute(
        CloseAcademyDatesCommand(
            start_at=datetime(2026, 1, 19, 6, tzinfo=UTC),
            end_at=datetime(2026, 1, 20, 6, tzinfo=UTC),
            reason="MLK day",
        )
    )
    assert result.cancelled == 0
    assert await real_db["session_occurrences"].count_documents({}) == 0
    assert notifier.calls == []


async def test_an_unexpected_error_on_one_date_still_notifies_the_cancelled_ones(
    real_db: Any, acad: str, monkeypatch: Any
) -> None:
    """B2: a non-domain error on date 2 of 3 used to escape the loop and drop
    the deferred notice for date 1, which no rerun ever resends."""
    _freeze_admin_clock(monkeypatch, AFTERNOON)
    await _seed_weekly(real_db, "sess-1")
    notifier = RecordingClosureNotifier()
    close = _frozen_closure(real_db, notifier, _real_maintain(real_db))
    real_execute = close._cancel.execute
    seen: list[str] = []

    async def flaky(cmd: Any) -> Any:
        seen.append(cmd.occurrence_id)
        if len(seen) == 2:
            raise RuntimeError("AutoReconnect: connection reset")
        return await real_execute(cmd)

    close._cancel.execute = flaky
    result = await close.execute(
        CloseAcademyDatesCommand(
            start_at=datetime(2026, 1, 12, 6, tzinfo=UTC),
            end_at=datetime(2026, 2, 1, 6, tzinfo=UTC),
            reason="Facility closed",
        )
    )
    assert len(seen) == 3
    assert [d.status for d in result.dates] == ["cancelled", "skipped", "cancelled"]
    assert result.dates[1].skip_reason == "failed, retry"
    told = {n.start_at for call in notifier.calls for n in call["dates"]}
    assert result.dates[0].start_at in told and result.dates[2].start_at in told
    assert len(notifier.calls) == 1


async def test_preview_shows_dates_the_cancel_rules_would_refuse(real_db: Any) -> None:
    """F5: the dry run runs the cancel's own pre-commit checks, so a date in a
    frozen payout period shows as skipped in the preview, not would_cancel."""
    await _seed(real_db)

    class FrozenFirstDate:
        async def locked_status_for(self, *, coach_id: str, at: datetime) -> str | None:
            return "approved" if at < CLOSE_START + timedelta(days=1) else None

    with tenant_scope(ACADEMY):
        close = compose_occurrence_cancellations(real_db, None, _no_materialize)[
            "close_academy_dates"
        ]
        close._cancel._payout_lock = FrozenFirstDate()
        preview = await close.execute(_command(dry_run=True))
    assert [(d.occurrence_id, d.status) for d in preview.dates] == [
        ("occ-in-1", "skipped"),
        ("occ-in-2", "would_cancel"),
    ]
    assert "payout period" in (preview.dates[0].skip_reason or "")
    assert (await _statuses(real_db))["occ-in-1"] == "scheduled"
