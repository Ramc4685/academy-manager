"""Cancel ONE dated class — rain-out, sick coach, holiday (issue #671).

Until now the only cancel was the whole session (``CancelSession``), which
ends every enrollment and voids every future invoice. This use case calls
off a single ``session_occurrences`` row and makes the three downstream
readers agree:

* **Coach**: the occurrence is ``cancelled``; the day view and payroll readers
  already skip that status, and ``is_payable`` is cleared so the date can
  never be paid.
* **Billing**: ``is_billable`` is cleared and the ``OccurrenceBillingSync``
  port hands the date to the billing context, which excludes it from
  proration and credits each enrolled family its share of the month.
* **Roster**: one-time make-up / trial rows for the date are dropped and the
  make-up requests behind them re-opened, so nobody is listed for a class
  that will not run and the family can be offered another date.

Ordering matters: the occurrence CAS is the commit point. Everything after
it is best-effort and logged — a mail outage or a billing hiccup must never
report "could not cancel" for a class that is, in fact, cancelled. The
lifecycle event per enrolled student carries ``billing_result`` so an admin
can see when billing did not follow.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    EnrollmentQuery,
    MakeupReopener,
    OccurrenceBillingSync,
    OccurrenceCancellationNotifier,
    OccurrenceRosterPurge,
    SessionOccurrenceRepository,
    SessionQuery,
)
from backend.v2.contexts.enrollment.domain.errors import (
    OccurrenceAlreadyCancelled,
    OccurrenceNotFound,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.occurrence_cancellation import (
    assert_occurrence_cancellable,
)
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]

#: Enrollment rows that get a lifecycle event and a billing decision. A paused
#: family is included on purpose: a paused month is never invoiced, but a
#: pause that started mid-month leaves an invoice behind that billing may
#: still need to credit.
_AFFECTED_STATUSES = ("active", "paused")


class CancelSessionOccurrenceCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    reason: str = Field(min_length=1, max_length=500)
    actor_id: str | None = None
    #: ``False`` records the cancellation without emailing families/coach —
    #: for a date the academy has already announced by other means.
    notify: bool = True


class CancelSessionOccurrenceResult(BaseModel):
    model_config = {"frozen": True}

    occurrence: SessionOccurrence
    affected_enrollment_ids: tuple[str, ...] = ()
    roster_entries_removed: int = 0
    makeups_reopened: int = 0
    credits_issued: int = 0
    billing_result: str | None = None
    notified: bool = False


class CancelSessionOccurrence:
    def __init__(
        self,
        *,
        occurrences: SessionOccurrenceRepository,
        sessions: SessionQuery,
        enrollments: EnrollmentQuery,
        enrollment_events: EnrollmentEventRepository | None = None,
        occurrence_roster: OccurrenceRosterPurge | None = None,
        makeups: MakeupReopener | None = None,
        billing_sync: OccurrenceBillingSync | None = None,
        notifier: OccurrenceCancellationNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._occurrences = occurrences
        self._sessions = sessions
        self._enrollments = enrollments
        self._events = enrollment_events
        self._roster = occurrence_roster
        self._makeups = makeups
        self._billing = billing_sync
        self._notifier = notifier
        self._now = clock

    async def execute(self, cmd: CancelSessionOccurrenceCommand) -> CancelSessionOccurrenceResult:
        now = self._now()
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None:
            raise OccurrenceNotFound("no such class date", occurrence_id=cmd.occurrence_id)
        session_id = occurrence.template_session_id or occurrence.session_id
        session = await self._sessions.get(session_id)
        assert_occurrence_cancellable(occurrence, session=session, now=now)

        cancelled = await self._occurrences.cancel_scheduled(
            occurrence_id=cmd.occurrence_id,
            reason=cmd.reason,
            actor_id=cmd.actor_id,
            now=now,
        )
        if cancelled is None:
            # Lost the race: someone else cancelled (or completed) it between
            # the read and the CAS. Re-read so the error names the true state.
            latest = await self._occurrences.get(cmd.occurrence_id)
            if latest is not None and latest.status == "cancelled":
                raise OccurrenceAlreadyCancelled(
                    "this class date is already cancelled",
                    occurrence_id=cmd.occurrence_id,
                )
            assert_occurrence_cancellable(latest or occurrence, session=session, now=now)
            raise OccurrenceNotFound("no such class date", occurrence_id=cmd.occurrence_id)

        # --- past the commit point: everything below is best-effort -------
        roster_removed = await self._purge_roster(cmd.occurrence_id)
        makeups_reopened = await self._reopen_makeups(cmd.occurrence_id)

        rows = await self._enrollments.for_session_in_statuses(session_id, list(_AFFECTED_STATUSES))
        billing = await self._sync_billing(cancelled, session_id=session_id, cmd=cmd)
        credits: dict[str, Any] = dict(billing.get("credits") or {})
        billing_result = _billing_result(billing)

        for enrollment in rows:
            credit = credits.get(enrollment.enrollment_id)
            await self._record_event(
                enrollment_id=enrollment.enrollment_id,
                student_id=enrollment.student_id,
                session_id=session_id,
                occurrence=cancelled,
                cmd=cmd,
                now=now,
                billing_result=billing_result,
                credit_id=str(credit) if credit else None,
            )

        notified = False
        if cmd.notify:
            notified = await self._notify(cancelled, session_id=session_id, cmd=cmd)

        return CancelSessionOccurrenceResult(
            occurrence=cancelled,
            affected_enrollment_ids=tuple(row.enrollment_id for row in rows),
            roster_entries_removed=roster_removed,
            makeups_reopened=makeups_reopened,
            credits_issued=sum(1 for value in credits.values() if value),
            billing_result=billing_result,
            notified=notified,
        )

    async def _purge_roster(self, occurrence_id: str) -> int:
        if self._roster is None:
            return 0
        try:
            return len(await self._roster.remove_for_occurrence(occurrence_id))
        except Exception:
            log.exception(
                "enrollment.occurrence_roster_purge_failed",
                extra={"occurrence_id": occurrence_id},
            )
            return 0

    async def _reopen_makeups(self, occurrence_id: str) -> int:
        if self._makeups is None:
            return 0
        try:
            return await self._makeups.reopen_for_target_occurrence(occurrence_id)
        except Exception:
            log.exception(
                "enrollment.makeup_reopen_failed",
                extra={"occurrence_id": occurrence_id},
            )
            return 0

    async def _sync_billing(
        self,
        occurrence: SessionOccurrence,
        *,
        session_id: str,
        cmd: CancelSessionOccurrenceCommand,
    ) -> dict[str, Any]:
        if self._billing is None:
            log.error(
                "occurrence_billing_sync_unwired: occurrence_id=%s reached billing nowhere — "
                "the month is still billed in full",
                occurrence.occurrence_id,
            )
            return {"billing_result": "billing_sync_unwired"}
        try:
            return await self._billing.apply(
                occurrence_id=occurrence.occurrence_id,
                session_id=session_id,
                start_at=occurrence.start_at,
                reason=cmd.reason,
                actor_id=cmd.actor_id,
            )
        except Exception:
            log.exception(
                "occurrence_billing_sync_failed",
                extra={"occurrence_id": occurrence.occurrence_id},
            )
            return {"billing_result": "billing_sync_failed"}

    async def _record_event(
        self,
        *,
        enrollment_id: str,
        student_id: str,
        session_id: str,
        occurrence: SessionOccurrence,
        cmd: CancelSessionOccurrenceCommand,
        now: datetime,
        billing_result: str | None,
        credit_id: str | None,
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.record(
                EnrollmentLifecycleEvent(
                    event_id=str(new_ulid()),
                    academy_id=occurrence.academy_id,
                    event_type="occurrence_cancelled",
                    enrollment_id=enrollment_id,
                    session_id=session_id,
                    student_id=student_id,
                    actor_id=cmd.actor_id,
                    reason=cmd.reason,
                    effective_at=occurrence.start_at,
                    occurred_at=now,
                    billing_policy="cancelled_date_credited",
                    billing_result=billing_result,
                    credit_id=credit_id,
                    metadata={
                        "occurrence_id": occurrence.occurrence_id,
                        "start_at": occurrence.start_at.isoformat(),
                    },
                )
            )
        except Exception:
            log.exception(
                "enrollment.occurrence_cancelled_event_failed",
                extra={"occurrence_id": occurrence.occurrence_id, "enrollment_id": enrollment_id},
            )

    async def _notify(
        self,
        occurrence: SessionOccurrence,
        *,
        session_id: str,
        cmd: CancelSessionOccurrenceCommand,
    ) -> bool:
        if self._notifier is None:
            return False
        try:
            await self._notifier.occurrence_cancelled(
                session_id=session_id,
                occurrence_id=occurrence.occurrence_id,
                start_at=occurrence.start_at,
                reason=cmd.reason,
                actor_id=cmd.actor_id,
            )
            return True
        except Exception:
            log.exception(
                "enrollment.occurrence_cancelled_notify_failed",
                extra={"occurrence_id": occurrence.occurrence_id},
            )
            return False


def _billing_result(sync: dict[str, Any]) -> str | None:
    value = sync.get("billing_result")
    return str(value) if value is not None else None
