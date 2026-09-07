"""``CancelSessionOccurrence`` — the enrollment side of issue #671.

The fakes mirror the real stores where the real stores constrain us: the
occurrence repo's ``cancel_scheduled`` is a CAS that only matches a
``scheduled`` row (as the Mongo filter does), and the roster purge returns
what it removed rather than silently succeeding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.cancel_session_occurrence import (
    CancelSessionOccurrence,
    CancelSessionOccurrenceCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    OccurrenceAlreadyCancelled,
    OccurrenceNotCancellable,
    OccurrenceNotFound,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, SessionOccurrence

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
START = NOW + timedelta(days=3)


@dataclass
class FakeOccurrences:
    rows: dict[str, SessionOccurrence] = field(default_factory=dict)

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        return self.rows.get(occurrence_id)

    async def cancel_scheduled(
        self, *, occurrence_id: str, reason: str, actor_id: str | None, now: datetime
    ) -> SessionOccurrence | None:
        row = self.rows.get(occurrence_id)
        if row is None or row.status != "scheduled":
            # Exactly the Mongo filter: {occurrence_id, status: "scheduled"}.
            return None
        self.rows[occurrence_id] = row.model_copy(
            update={
                "status": "cancelled",
                "is_billable": False,
                "is_payable": False,
                "cancellation_reason": reason,
                "cancelled_at": now,
                "cancelled_by": actor_id,
            }
        )
        return self.rows[occurrence_id]


@dataclass
class FakeSessions:
    rows: dict[str, Session] = field(default_factory=dict)

    async def get(self, session_id: str) -> Session | None:
        return self.rows.get(session_id)


@dataclass
class FakeEnrollments:
    rows: list[Enrollment] = field(default_factory=list)

    async def for_session_in_statuses(
        self, session_id: str, statuses: list[str]
    ) -> list[Enrollment]:
        return [row for row in self.rows if row.session_id == session_id and row.status in statuses]


@dataclass
class FakeEvents:
    recorded: list[Any] = field(default_factory=list)

    async def record(self, event: Any) -> None:
        self.recorded.append(event)


@dataclass
class FakeRosterEntry:
    """Mirrors ``OccurrenceRosterEntry``: the purge hands the caller the rows
    it deleted, and each carries the student who lost the seat."""

    entry_id: str
    student_id: str


@dataclass
class FakeRoster:
    entries: dict[str, list[FakeRosterEntry]] = field(default_factory=dict)

    async def remove_for_occurrence(self, occurrence_id: str) -> list[FakeRosterEntry]:
        return self.entries.pop(occurrence_id, [])


@dataclass
class FakeMakeups:
    reopened: list[tuple[str, datetime]] = field(default_factory=list)
    count: int = 0

    async def reopen_for_target_occurrence(
        self, occurrence_id: str, *, expires_at: datetime
    ) -> int:
        self.reopened.append((occurrence_id, expires_at))
        return self.count


@dataclass
class FakeTrials:
    reopened: list[str] = field(default_factory=list)
    student_ids: list[str] = field(default_factory=list)

    async def reopen_for_assigned_occurrence(self, occurrence_id: str) -> list[str]:
        self.reopened.append(occurrence_id)
        return list(self.student_ids)


@dataclass
class FakeBilling:
    calls: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    boom: bool = False

    async def apply(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("ledger unavailable")
        return self.result


@dataclass
class FakeNotifier:
    calls: list[dict[str, Any]] = field(default_factory=list)
    boom: bool = False

    async def occurrence_cancelled(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("mail down")


def _occurrence(**overrides: Any) -> SessionOccurrence:
    base: dict[str, Any] = {
        "occurrence_id": "occ-1",
        "academy_id": "acad",
        "session_id": "sess-1",
        "start_at": START,
        "end_at": START + timedelta(hours=1),
        "scheduled_coach_id": "coach-1",
    }
    base.update(overrides)
    return SessionOccurrence(**base)


def _session(status: str = "scheduled") -> Session:
    return Session(
        session_id="sess-1",
        academy_id="acad",
        coach_id="coach-1",
        title="Beginner badminton",
        location="Court 1",
        start_at=START,
        end_at=START + timedelta(hours=1),
        capacity=10,
        status=status,  # type: ignore[arg-type]
    )


def _enrollment(enrollment_id: str, student_id: str, status: str = "active") -> Enrollment:
    return Enrollment(
        enrollment_id=enrollment_id,
        academy_id="acad",
        session_id="sess-1",
        student_id=student_id,
        status=status,  # type: ignore[arg-type]
    )


def _build(
    *,
    occurrences: FakeOccurrences,
    enrollments: FakeEnrollments | None = None,
    roster: FakeRoster | None = None,
    makeups: FakeMakeups | None = None,
    trials: FakeTrials | None = None,
    billing: FakeBilling | None = None,
    notifier: FakeNotifier | None = None,
    events: FakeEvents | None = None,
) -> CancelSessionOccurrence:
    return CancelSessionOccurrence(
        occurrences=occurrences,  # type: ignore[arg-type]
        sessions=FakeSessions({"sess-1": _session()}),  # type: ignore[arg-type]
        enrollments=enrollments or FakeEnrollments(),  # type: ignore[arg-type]
        enrollment_events=events,  # type: ignore[arg-type]
        occurrence_roster=roster,  # type: ignore[arg-type]
        makeups=makeups,  # type: ignore[arg-type]
        trials=trials,  # type: ignore[arg-type]
        billing_sync=billing,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_cancel_stamps_the_row_and_stops_billing_and_payroll() -> None:
    occurrences = FakeOccurrences({"occ-1": _occurrence()})
    use_case = _build(occurrences=occurrences, billing=FakeBilling(result={"credits": {}}))

    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="gym flooded", actor_id="u-1")
    )

    stored = occurrences.rows["occ-1"]
    assert stored.status == "cancelled"
    assert stored.is_billable is False
    assert stored.is_payable is False
    assert stored.cancellation_reason == "gym flooded"
    assert stored.cancelled_at == NOW
    assert stored.cancelled_by == "u-1"
    assert result.occurrence.status == "cancelled"


@pytest.mark.asyncio
async def test_missing_occurrence_is_a_not_found() -> None:
    use_case = _build(occurrences=FakeOccurrences())
    with pytest.raises(OccurrenceNotFound):
        await use_case.execute(CancelSessionOccurrenceCommand(occurrence_id="ghost", reason="rain"))


@pytest.mark.asyncio
async def test_cancelling_twice_is_refused() -> None:
    occurrences = FakeOccurrences({"occ-1": _occurrence()})
    use_case = _build(occurrences=occurrences, billing=FakeBilling())
    await use_case.execute(CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain"))

    with pytest.raises(OccurrenceAlreadyCancelled):
        await use_case.execute(
            CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain again")
        )


@pytest.mark.asyncio
async def test_past_date_is_refused_and_never_written() -> None:
    past = _occurrence(start_at=NOW - timedelta(days=1), end_at=NOW - timedelta(days=1, hours=-1))
    occurrences = FakeOccurrences({"occ-1": past})
    use_case = _build(occurrences=occurrences)

    with pytest.raises(OccurrenceNotCancellable):
        await use_case.execute(
            CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="too late")
        )
    assert occurrences.rows["occ-1"].status == "scheduled"


@pytest.mark.asyncio
async def test_roster_rows_dropped_and_makeups_reopened() -> None:
    roster = FakeRoster(
        {"occ-1": [FakeRosterEntry("entry-1", "st-m"), FakeRosterEntry("entry-2", "st-t")]}
    )
    makeups = FakeMakeups(count=2)
    trials = FakeTrials(student_ids=["st-t"])
    notifier = FakeNotifier()
    use_case = _build(
        occurrences=FakeOccurrences({"occ-1": _occurrence()}),
        roster=roster,
        makeups=makeups,
        trials=trials,
        billing=FakeBilling(),
        notifier=notifier,
    )

    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="coach sick")
    )

    assert result.roster_entries_removed == 2
    assert result.makeups_reopened == 2
    assert result.trials_reopened == 1
    assert "occ-1" not in roster.entries
    assert trials.reopened == ["occ-1"]
    # A re-opened make-up gets a FRESH window: keeping the lapsed one hands it
    # straight back to the expiry sweep and the family loses the entitlement.
    assert makeups.reopened[0][0] == "occ-1"
    assert makeups.reopened[0][1] > NOW
    # The make-up and trial families have no enrollment on this session, so
    # they only hear about the cancellation through extra_student_ids.
    assert notifier.calls[0]["extra_student_ids"] == ["st-m", "st-t"]


@pytest.mark.asyncio
async def test_only_credited_families_are_told_about_a_credit() -> None:
    billing = FakeBilling(
        result={"billing_result": "credited=1,skipped=1", "credits": {"enr-1": "cr-1"}}
    )
    notifier = FakeNotifier()
    use_case = _build(
        occurrences=FakeOccurrences({"occ-1": _occurrence()}),
        enrollments=FakeEnrollments([_enrollment("enr-1", "st-1"), _enrollment("enr-2", "st-2")]),
        billing=billing,
        notifier=notifier,
    )

    await use_case.execute(CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain"))

    assert notifier.calls[0]["credited_student_ids"] == ["st-1"]
    assert notifier.calls[0]["billing_warning"] is None


@pytest.mark.asyncio
async def test_a_failed_billing_sync_warns_the_staff_and_promises_nobody_a_credit() -> None:
    notifier = FakeNotifier()
    use_case = _build(
        occurrences=FakeOccurrences({"occ-1": _occurrence()}),
        enrollments=FakeEnrollments([_enrollment("enr-1", "st-1")]),
        billing=FakeBilling(boom=True),
        notifier=notifier,
    )

    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain")
    )

    assert result.billing_result == "billing_sync_failed"
    assert notifier.calls[0]["credited_student_ids"] == []
    assert "no credits were issued" in notifier.calls[0]["billing_warning"]


@pytest.mark.asyncio
async def test_billing_port_is_called_with_the_date_and_credits_are_counted() -> None:
    billing = FakeBilling(
        result={"billing_result": "credited=2", "credits": {"enr-1": "cr-1", "enr-2": "cr-2"}}
    )
    enrollments = FakeEnrollments([_enrollment("enr-1", "st-1"), _enrollment("enr-2", "st-2")])
    events = FakeEvents()
    use_case = _build(
        occurrences=FakeOccurrences({"occ-1": _occurrence()}),
        enrollments=enrollments,
        billing=billing,
        events=events,
    )

    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="holiday", actor_id="u-1")
    )

    assert billing.calls == [
        {
            "occurrence_id": "occ-1",
            "session_id": "sess-1",
            "start_at": START,
            "reason": "holiday",
            "actor_id": "u-1",
        }
    ]
    assert result.credits_issued == 2
    assert result.billing_result == "credited=2"
    assert sorted(result.affected_enrollment_ids) == ["enr-1", "enr-2"]
    assert {event.credit_id for event in events.recorded} == {"cr-1", "cr-2"}
    assert {event.event_type for event in events.recorded} == {"occurrence_cancelled"}


@pytest.mark.asyncio
async def test_paused_families_are_included() -> None:
    enrollments = FakeEnrollments(
        [
            _enrollment("enr-active", "st-1"),
            _enrollment("enr-paused", "st-2", status="paused"),
            _enrollment("enr-gone", "st-3", status="cancelled"),
        ]
    )
    use_case = _build(
        occurrences=FakeOccurrences({"occ-1": _occurrence()}),
        enrollments=enrollments,
        billing=FakeBilling(),
    )

    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain")
    )

    assert sorted(result.affected_enrollment_ids) == ["enr-active", "enr-paused"]


@pytest.mark.asyncio
async def test_billing_failure_never_undoes_the_cancel() -> None:
    occurrences = FakeOccurrences({"occ-1": _occurrence()})
    use_case = _build(occurrences=occurrences, billing=FakeBilling(boom=True))

    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain")
    )

    assert occurrences.rows["occ-1"].status == "cancelled"
    assert result.billing_result == "billing_sync_failed"
    assert result.credits_issued == 0


@pytest.mark.asyncio
async def test_unwired_billing_is_reported_not_hidden() -> None:
    use_case = _build(occurrences=FakeOccurrences({"occ-1": _occurrence()}))
    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain")
    )
    assert result.billing_result == "billing_sync_unwired"


@pytest.mark.asyncio
async def test_notifier_is_called_and_a_mail_outage_is_swallowed() -> None:
    notifier = FakeNotifier()
    use_case = _build(
        occurrences=FakeOccurrences({"occ-1": _occurrence()}),
        billing=FakeBilling(),
        notifier=notifier,
    )
    result = await use_case.execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-1", reason="rain", actor_id="u-1")
    )
    assert result.notified is True
    assert notifier.calls[0]["occurrence_id"] == "occ-1"

    broken = FakeNotifier(boom=True)
    occurrences = FakeOccurrences({"occ-2": _occurrence(occurrence_id="occ-2")})
    result = await _build(occurrences=occurrences, billing=FakeBilling(), notifier=broken).execute(
        CancelSessionOccurrenceCommand(occurrence_id="occ-2", reason="rain")
    )
    assert result.notified is False
    assert occurrences.rows["occ-2"].status == "cancelled"


@pytest.mark.asyncio
async def test_notify_false_skips_the_mail() -> None:
    notifier = FakeNotifier()
    use_case = _build(
        occurrences=FakeOccurrences({"occ-1": _occurrence()}),
        billing=FakeBilling(),
        notifier=notifier,
    )
    result = await use_case.execute(
        CancelSessionOccurrenceCommand(
            occurrence_id="occ-1", reason="already told them", notify=False
        )
    )
    assert result.notified is False
    assert notifier.calls == []
