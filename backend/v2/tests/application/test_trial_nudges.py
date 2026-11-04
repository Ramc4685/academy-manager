"""Trial nudges (AI strategy Phase 1 #3): reminder the day before an approved
trial, one re-engagement after a no-show. Selection and idempotency with
fakes that mirror the Mongo claim's semantics (a second run sends nothing;
a mark from another academy is a no-op)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.contexts.enrollment.application.use_cases.trial_nudges import (
    NO_SHOW_FOLLOW_UP_AFTER,
    NO_SHOW_LOOKBACK,
    SendTrialNoShowFollowUps,
    SendTrialReminders,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest

pytestmark = pytest.mark.asyncio

ACADEMY_ID = "acad-1"
CHICAGO = ZoneInfo("America/Chicago")
#: 16:00 local on 2026-11-04 (the reminder job's hour).
LOCAL_NOW = datetime(2026, 11, 4, 16, 0, tzinfo=CHICAGO)


def _trial(
    request_id: str,
    *,
    status: str = "approved",
    occurrence_id: str | None = "occ-1",
    parent: str = "parent-1",
    created_at: datetime | None = None,
    outcome: str | None = None,
    outcome_at: datetime | None = None,
    linked_application_id: str | None = None,
) -> TrialRequest:
    return TrialRequest(
        request_id=request_id,
        academy_id=ACADEMY_ID,
        parent_user_id=parent,
        student_ref="prospective",
        prospective_child_name="Ava",
        requested_session_id="sess-1",
        preferred_start="2026-11-01",
        preferred_end="2026-11-30",
        status=status,  # type: ignore[arg-type]
        assigned_occurrence_id=occurrence_id,
        linked_application_id=linked_application_id,
        created_at=created_at or datetime(2026, 10, 20, tzinfo=UTC),
        outcome=outcome,  # type: ignore[arg-type]
        outcome_at=outcome_at,
    )


def _occurrence(occurrence_id: str, *, start_local: datetime, status: str = "scheduled"):
    start = start_local.astimezone(UTC)
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id=ACADEMY_ID,
        session_id="sess-1",
        start_at=start,
        end_at=start + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        scheduled_coach_id="coach-1",
    )


class FakeTrials:
    def __init__(self, trials: list[TrialRequest]) -> None:
        self._trials = trials

    async def list_by_status(self, status: str | None) -> list[TrialRequest]:
        return [t for t in self._trials if status is None or t.status == status]

    async def list_for_parent(self, parent_user_id: str) -> list[TrialRequest]:
        return [t for t in self._trials if t.parent_user_id == parent_user_id]


class FakeOccurrences:
    def __init__(self, occurrences: list[SessionOccurrence]) -> None:
        self._by_id = {o.occurrence_id: o for o in occurrences}

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        return self._by_id.get(occurrence_id)


class FakeSendClaimRepository:
    """In-memory stand-in for ``MongoTrialNudgeSendRepository``: one claim per
    ``(academy_id, subject_id, nudge_key)``; a ``failed`` row may be
    re-claimed, a ``sent`` row never; marks are filtered on academy_id."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def try_claim(self, *, academy_id: str, subject_id: str, nudge_key: str):
        key = (academy_id, subject_id, nudge_key)
        for row in self.rows.values():
            if row["key"] == key:
                if row["status"] == "failed":
                    row["status"] = "queued"
                    return row
                return None
        send_id = f"send-{len(self.rows)}"
        row = {"send_id": send_id, "key": key, "status": "queued"}
        self.rows[send_id] = row
        return row

    async def mark_sent(self, academy_id: str, send_id: str) -> None:
        row = self.rows.get(send_id)
        if row is None or row["key"][0] != academy_id:
            return  # Mongo: a filter that matches no row is a no-op (#880)
        row["status"] = "sent"

    async def mark_failed(self, academy_id: str, send_id: str, reason: str) -> None:
        row = self.rows.get(send_id)
        if row is None or row["key"][0] != academy_id:
            return
        row["status"] = "failed"

    def statuses(self) -> list[tuple[tuple[str, str, str], str]]:
        return [(row["key"], row["status"]) for row in self.rows.values()]


class FakeNotifier:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.reminders: list[tuple[str, datetime]] = []
        self.no_shows: list[str] = []

    async def trial_reminder(self, *, trial: TrialRequest, local_start: datetime) -> bool:
        self.reminders.append((trial.request_id, local_start))
        return self.ok

    async def trial_no_show(self, *, trial: TrialRequest) -> bool:
        self.no_shows.append(trial.request_id)
        return self.ok


class FakeSwitch:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    async def is_enabled(self, academy_id: str) -> bool:
        return self.enabled


def _reminders(trials, occurrences, *, send_repo=None, notifier=None, switch=None):
    return SendTrialReminders(
        trials=FakeTrials(trials),
        occurrences=FakeOccurrences(occurrences),
        send_repo=send_repo or FakeSendClaimRepository(),
        notifier=notifier or FakeNotifier(),
        switch=switch or FakeSwitch(),
    )


# --- reminders ---------------------------------------------------------------


async def test_reminds_an_approved_trial_whose_date_is_tomorrow_local() -> None:
    tomorrow_9am = datetime(2026, 11, 5, 9, 0, tzinfo=CHICAGO)
    notifier = FakeNotifier()
    send_repo = FakeSendClaimRepository()
    job = _reminders(
        [_trial("t1")],
        [_occurrence("occ-1", start_local=tomorrow_9am)],
        send_repo=send_repo,
        notifier=notifier,
    )

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 1

    assert notifier.reminders == [("t1", tomorrow_9am)]
    assert send_repo.statuses() == [((ACADEMY_ID, "t1", "trial_reminder"), "sent")]


async def test_second_run_sends_nothing() -> None:
    notifier = FakeNotifier()
    send_repo = FakeSendClaimRepository()
    job = _reminders(
        [_trial("t1")],
        [_occurrence("occ-1", start_local=datetime(2026, 11, 5, 9, 0, tzinfo=CHICAGO))],
        send_repo=send_repo,
        notifier=notifier,
    )

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 1
    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 0
    # A late tick the next morning, still before the class, is also silent.
    assert (
        await job.execute(
            academy_id=ACADEMY_ID, local_now=datetime(2026, 11, 5, 7, 0, tzinfo=CHICAGO)
        )
        == 0
    )

    assert len(notifier.reminders) == 1


async def test_a_trial_on_another_day_or_cancelled_or_not_approved_is_skipped() -> None:
    tomorrow = datetime(2026, 11, 5, 9, 0, tzinfo=CHICAGO)
    notifier = FakeNotifier()
    job = _reminders(
        [
            _trial("today", occurrence_id="occ-today"),
            _trial("day-after", occurrence_id="occ-day-after"),
            _trial("cancelled", occurrence_id="occ-cancelled"),
            _trial("pending", status="pending", occurrence_id="occ-ok"),
            _trial("no-date", occurrence_id=None),
            _trial("missing-date", occurrence_id="occ-missing"),
            # Just before midnight local is still tomorrow on the academy's clock.
            _trial("late", occurrence_id="occ-late"),
        ],
        [
            _occurrence("occ-today", start_local=datetime(2026, 11, 4, 18, 0, tzinfo=CHICAGO)),
            _occurrence("occ-day-after", start_local=tomorrow + timedelta(days=1)),
            _occurrence("occ-cancelled", start_local=tomorrow, status="cancelled"),
            _occurrence("occ-ok", start_local=tomorrow),
            _occurrence("occ-late", start_local=datetime(2026, 11, 5, 23, 30, tzinfo=CHICAGO)),
        ],
        notifier=notifier,
    )

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 1
    assert [r[0] for r in notifier.reminders] == ["late"]


async def test_switch_off_sends_and_claims_nothing() -> None:
    send_repo = FakeSendClaimRepository()
    job = _reminders(
        [_trial("t1")],
        [_occurrence("occ-1", start_local=datetime(2026, 11, 5, 9, 0, tzinfo=CHICAGO))],
        send_repo=send_repo,
        switch=FakeSwitch(enabled=False),
    )

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 0
    assert send_repo.rows == {}


async def test_a_failed_send_keeps_the_claim_retryable() -> None:
    send_repo = FakeSendClaimRepository()
    broken = FakeNotifier(ok=False)
    occurrences = [_occurrence("occ-1", start_local=datetime(2026, 11, 5, 9, 0, tzinfo=CHICAGO))]
    job = _reminders([_trial("t1")], occurrences, send_repo=send_repo, notifier=broken)

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 0
    assert send_repo.statuses() == [((ACADEMY_ID, "t1", "trial_reminder"), "failed")]

    working = FakeNotifier()
    retry = _reminders([_trial("t1")], occurrences, send_repo=send_repo, notifier=working)
    assert await retry.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 1
    assert send_repo.statuses() == [((ACADEMY_ID, "t1", "trial_reminder"), "sent")]


async def test_fake_mark_calls_from_another_academy_are_no_ops() -> None:
    send_repo = FakeSendClaimRepository()
    claim = await send_repo.try_claim(academy_id="acad-a", subject_id="t1", nudge_key="k")
    assert claim is not None

    await send_repo.mark_sent("acad-b", claim["send_id"])
    await send_repo.mark_failed("acad-b", claim["send_id"], "x")

    assert send_repo.rows[claim["send_id"]]["status"] == "queued"


# --- no-show follow-ups -------------------------------------------------------


def _no_show(request_id: str, *, days_ago: int, **kwargs) -> TrialRequest:
    return _trial(
        request_id,
        status="completed",
        outcome="no_show",
        outcome_at=LOCAL_NOW - timedelta(days=days_ago),
        **kwargs,
    )


def _no_shows(trials, *, send_repo=None, notifier=None, switch=None):
    return SendTrialNoShowFollowUps(
        trials=FakeTrials(trials),
        send_repo=send_repo or FakeSendClaimRepository(),
        notifier=notifier or FakeNotifier(),
        switch=switch or FakeSwitch(),
    )


async def test_no_show_gets_one_follow_up_after_the_delay_and_never_again() -> None:
    notifier = FakeNotifier()
    send_repo = FakeSendClaimRepository()
    job = _no_shows([_no_show("t1", days_ago=3)], send_repo=send_repo, notifier=notifier)

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 1
    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 0
    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW + timedelta(days=10)) == 0

    assert notifier.no_shows == ["t1"]
    assert send_repo.statuses() == [((ACADEMY_ID, "t1", "trial_no_show"), "sent")]


async def test_no_show_selection() -> None:
    notifier = FakeNotifier()
    # One parent per trial, so only the outcome and its timing decide.
    trials = [
        _no_show("too-recent", days_ago=1, parent="p1"),
        _no_show("too-old", days_ago=NO_SHOW_LOOKBACK.days + 1, parent="p2"),
        _no_show("registered", days_ago=4, linked_application_id="app-1", parent="p3"),
        _trial(
            "came",
            status="completed",
            outcome="came",
            outcome_at=LOCAL_NOW - timedelta(days=4),
            parent="p4",
        ),
        _trial("approved", status="approved", parent="p5"),
        _no_show("due", days_ago=NO_SHOW_FOLLOW_UP_AFTER.days, parent="p6"),
    ]
    job = _no_shows(trials, notifier=notifier)

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 1
    assert notifier.no_shows == ["due"]


async def test_a_family_that_rebooked_is_not_nudged() -> None:
    notifier = FakeNotifier()
    missed = _no_show(
        "missed", days_ago=4, parent="p-1", created_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    rebooked = _trial(
        "again",
        status="pending",
        occurrence_id=None,
        parent="p-1",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    # A denied later request, or another family's request, does not count.
    denied = _trial(
        "denied",
        status="denied",
        occurrence_id=None,
        parent="p-2",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    other_missed = _no_show(
        "other", days_ago=4, parent="p-2", created_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    job = _no_shows([missed, rebooked, denied, other_missed], notifier=notifier)

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 1
    assert notifier.no_shows == ["other"]


async def test_no_show_switch_off_sends_nothing() -> None:
    notifier = FakeNotifier()
    job = _no_shows([_no_show("t1", days_ago=3)], notifier=notifier, switch=FakeSwitch(False))

    assert await job.execute(academy_id=ACADEMY_ID, local_now=LOCAL_NOW) == 0
    assert notifier.no_shows == []
