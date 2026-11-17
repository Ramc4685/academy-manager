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

from backend.v2.composition.occurrence_cancellation import compose_occurrence_cancellations
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

    async def academy_closed(self, *, dates, reason, actor_id) -> int:
        self.calls.append({"dates": list(dates), "reason": reason, "actor_id": actor_id})
        return 1


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
        close = compose_occurrence_cancellations(real_db, notifier, None)["close_academy_dates"]
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
        close = compose_occurrence_cancellations(real_db, notifier, None)["close_academy_dates"]
        close._notifier = notifier
        await close.execute(_command())
        again = await close.execute(_command())
    assert again.cancelled == 0 and again.dates == ()
    assert len(notifier.calls) == 1


async def test_closure_refuses_a_range_past_the_materialisation_window(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        close = compose_occurrence_cancellations(real_db, None, None)["close_academy_dates"]
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
