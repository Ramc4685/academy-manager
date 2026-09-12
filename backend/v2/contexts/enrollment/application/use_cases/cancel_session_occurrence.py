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
* **Roster**: one-time make-up / trial rows for the date are dropped, and the
  make-up AND trial requests behind them are re-opened — a make-up with a
  fresh window, so the next expiry sweep cannot swallow an entitlement the
  academy already granted. Those students hold no enrollment on the session,
  so their ids are handed to the notifier explicitly; without that they lose
  a seat in silence and arrive at a closed gym.

The email is honest about the money: only the families billing actually
credited are told about a credit, and the staff copy carries a warning when
the sync did not run at all.

Ordering matters: the occurrence CAS is the commit point. Everything after
it is best-effort and logged — a mail outage or a billing hiccup must never
report "could not cancel" for a class that is, in fact, cancelled. The
lifecycle event per enrolled student carries ``billing_result`` so an admin
can see when billing did not follow.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    EnrollmentQuery,
    MakeupPolicyLookup,
    MakeupReopener,
    OccurrenceBillingSync,
    OccurrenceCancellationNotifier,
    OccurrenceRosterPurge,
    SessionOccurrenceRepository,
    SessionQuery,
    TrialReopener,
)
from backend.v2.contexts.enrollment.domain.errors import (
    OccurrenceAlreadyCancelled,
    OccurrenceNotFound,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import ACTIVE_OR_PAUSED, SessionOccurrence
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
#: Issue #642: domain ``ACTIVE_OR_PAUSED``, same two statuses this always
#: meant. Deliberately NOT widened to ``LIVE`` here — whether a held family
#: is owed a credit for a called-off class is a billing question this slice
#: does not answer.
_AFFECTED_STATUSES = ACTIVE_OR_PAUSED

#: Fallback window for a re-opened make-up when the academy's own
#: ``ParentSelfServicePolicy.makeup_expiry_days`` cannot be read. Mirrors that
#: model's default; the policy repo is the source of truth when it is wired.
_DEFAULT_MAKEUP_EXPIRY_DAYS = 30


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
    trials_reopened: int = 0
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
        trials: TrialReopener | None = None,
        makeup_policies: MakeupPolicyLookup | None = None,
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
        self._trials = trials
        self._makeup_policies = makeup_policies
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
        removed_entries = await self._purge_roster(cmd.occurrence_id)
        makeups_reopened = await self._reopen_makeups(cmd.occurrence_id, now=now)
        trial_student_ids = await self._reopen_trials(cmd.occurrence_id)
        # Make-up and trial students hold a one-time seat and no enrollment on
        # this session, so the roster audience never reaches them. Their seat
        # has just been deleted; telling them is the whole point (#671).
        one_time_student_ids = _distinct(
            [str(getattr(entry, "student_id", "") or "") for entry in removed_entries]
            + list(trial_student_ids)
        )

        rows = await self._enrollments.for_session_in_statuses(
            session_id, sorted(_AFFECTED_STATUSES)
        )
        billing = await self._sync_billing(cancelled, session_id=session_id, cmd=cmd)
        credits: dict[str, Any] = dict(billing.get("credits") or {})
        billing_result = _billing_result(billing)
        # Only the families billing actually credited may be told they were
        # credited: the sync can fail wholesale, and individual families are
        # skipped (void invoice, before billing start, date not billed).
        credited_student_ids = [row.student_id for row in rows if credits.get(row.enrollment_id)]

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
            notified = await self._notify(
                cancelled,
                session_id=session_id,
                cmd=cmd,
                extra_student_ids=one_time_student_ids,
                credited_student_ids=credited_student_ids,
                billing_warning=_billing_warning(billing_result),
            )

        return CancelSessionOccurrenceResult(
            occurrence=cancelled,
            affected_enrollment_ids=tuple(row.enrollment_id for row in rows),
            roster_entries_removed=len(removed_entries),
            makeups_reopened=makeups_reopened,
            trials_reopened=len(trial_student_ids),
            credits_issued=sum(1 for value in credits.values() if value),
            billing_result=billing_result,
            notified=notified,
        )

    async def _purge_roster(self, occurrence_id: str) -> list[Any]:
        if self._roster is None:
            return []
        try:
            return list(await self._roster.remove_for_occurrence(occurrence_id))
        except Exception:
            log.exception(
                "enrollment.occurrence_roster_purge_failed",
                extra={"occurrence_id": occurrence_id},
            )
            return []

    async def _reopen_makeups(self, occurrence_id: str, *, now: datetime) -> int:
        if self._makeups is None:
            return 0
        try:
            return await self._makeups.reopen_for_target_occurrence(
                occurrence_id, expires_at=await self._makeup_window_end(now)
            )
        except Exception:
            log.exception(
                "enrollment.makeup_reopen_failed",
                extra={"occurrence_id": occurrence_id},
            )
            return 0

    async def _makeup_window_end(self, now: datetime) -> datetime:
        """A FRESH window for a make-up whose class the academy called off.

        The request may have been granted under a window that has since
        lapsed; re-opening it with that stale ``expires_at`` hands it straight
        to ``expire_pending_before``, and the family loses an entitlement it
        was already given. The academy's own ``makeup_expiry_days`` is used
        when it can be read, the domain default otherwise.
        """
        days = _DEFAULT_MAKEUP_EXPIRY_DAYS
        if self._makeup_policies is not None:
            try:
                policy = await self._makeup_policies.get_or_default()
                days = int(getattr(policy, "makeup_expiry_days", days))
            except Exception:  # pragma: no cover - defensive
                log.exception("enrollment.makeup_policy_read_failed")
        return now + timedelta(days=max(days, 1))

    async def _reopen_trials(self, occurrence_id: str) -> list[str]:
        """Trials assigned to the cancelled date, back to pending (#671).

        Without this a trial stays ``approved`` against a class that will not
        run while its roster seat is already deleted, so nothing re-offers it
        and the trial is silently lost.
        """
        if self._trials is None:
            return []
        try:
            return list(await self._trials.reopen_for_assigned_occurrence(occurrence_id))
        except Exception:
            log.exception(
                "enrollment.trial_reopen_failed",
                extra={"occurrence_id": occurrence_id},
            )
            return []

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
        extra_student_ids: list[str],
        credited_student_ids: list[str],
        billing_warning: str | None,
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
                extra_student_ids=extra_student_ids,
                credited_student_ids=credited_student_ids,
                billing_warning=billing_warning,
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


#: Billing outcomes where NO family was credited at all, so the staff copy has
#: to say so rather than let the admin assume the money side followed (#671).
_BILLING_FAILURES: dict[str, str] = {
    "billing_sync_failed": (
        "Billing did not run for this cancellation — no credits were issued. "
        "Check the class dates and credit the families by hand."
    ),
    "billing_sync_unwired": (
        "Billing is not wired for occurrence cancellations in this deployment — "
        "no credits were issued."
    ),
}


def _billing_warning(billing_result: str | None) -> str | None:
    if billing_result is None:
        return None
    return _BILLING_FAILURES.get(billing_result)


def _distinct(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
