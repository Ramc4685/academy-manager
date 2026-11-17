"""Academy-wide closure: call off every class in a date range in one step.

Thanksgiving week or a facility closure used to mean cancelling each class
date by hand, one credit run and one family email per date. This use case is
a loop over ``CancelSessionOccurrence`` — the same CAS, billing sync, credit,
roster purge, make-up/trial re-open and lifecycle event per date — with the
per-date family email deferred, so each family gets ONE summary listing every
date it loses (``AcademyClosureNotifier``). Trial guests still get their own
per-trial notice from the cancel use case.

There is one credit decision for the whole closure: every cancelled date goes
through the existing occurrence-cancel credit rule. Nothing here prices or
credits anything itself.

Dated rows exist only inside the 60-day materialisation window that class
create/edit writes, so the closure first re-runs that maintenance for every
live recurring class (idempotent) and refuses a range that ends past the
window: a date with no row would silently stay on the schedule.

Re-running the same closure cancels nothing twice: already-cancelled dates
are skipped by the cancel CAS. A date that fails for an unexpected reason is
reported as "failed, retry" and the rest go ahead; the summary for every date
that WAS cancelled is still sent. Known gap: if the process dies mid-run, the
dates cancelled before the crash are never in a summary (a rerun skips them).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.ports import (
    OCCURRENCE_WINDOW,
    AcademyClosureNotifier,
    ClosedClassDate,
    ClosureNotice,
    LiveSessionLister,
    OccurrenceMaterializer,
)
from backend.v2.contexts.enrollment.application.use_cases.cancel_session_occurrence import (
    CancelSessionOccurrence,
    CancelSessionOccurrenceCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.trial_guest_booking import (
    BookableOccurrenceQuery,
)
from backend.v2.contexts.enrollment.domain.errors import ClosureRangeInvalid
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.shared.http.errors import DomainError

log = logging.getLogger(__name__)

FAILED_RETRY = "failed, retry"


class CloseAcademyDatesCommand(BaseModel):
    model_config = {"frozen": True}

    #: Inclusive start / exclusive end, UTC (the route converts local dates).
    start_at: datetime
    end_at: datetime
    reason: str = Field(min_length=1, max_length=500)
    actor_id: str | None = None
    notify: bool = True
    #: Preview: list the dates that would be cancelled (and the ones the
    #: cancel rules would refuse), write nothing but the idempotent
    #: materialisation.
    dry_run: bool = False


class ClosureDate(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    start_at: datetime
    status: Literal["cancelled", "would_cancel", "skipped"]
    skip_reason: str | None = None
    credits_issued: int = 0
    #: The cancel's money warning (credits not applied): the admin running the
    #: closure is not on the staff summary email, so it is shown here.
    billing_warning: str | None = None


class CloseAcademyDatesResult(BaseModel):
    model_config = {"frozen": True}

    dates: tuple[ClosureDate, ...] = ()
    cancelled: int = 0
    skipped: int = 0
    credits_issued: int = 0
    families_affected: int = 0
    families_notified: int = 0
    notice_failed: bool = False


class CloseAcademyDates:
    def __init__(
        self,
        *,
        cancel: CancelSessionOccurrence,
        occurrences: BookableOccurrenceQuery,
        sessions: LiveSessionLister,
        materialize: OccurrenceMaterializer,
        notifier: AcademyClosureNotifier | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._cancel = cancel
        self._occurrences = occurrences
        self._sessions = sessions
        self._materialize = materialize
        self._notifier = notifier
        self._now = clock

    async def execute(self, cmd: CloseAcademyDatesCommand) -> CloseAcademyDatesResult:
        now = self._now()
        if cmd.end_at <= cmd.start_at:
            raise ClosureRangeInvalid("the closure must end on or after the day it starts")
        if cmd.end_at <= now:
            raise ClosureRangeInvalid("the closure is already over")
        if cmd.end_at > now + OCCURRENCE_WINDOW:
            raise ClosureRangeInvalid("a closure can be set at most 60 days ahead")

        # A materialisation failure stops the run before anything is cancelled:
        # a date with no row would silently stay on the schedule.
        for session in await self._sessions.list_live():
            await self._materialize(session)
        rows = await self._occurrences.list_upcoming_scheduled_between(
            start_at=max(cmd.start_at, now), end_at=cmd.end_at - timedelta(microseconds=1)
        )

        dates_out: list[ClosureDate] = []
        notices: list[ClosedClassDate] = []
        try:
            for row in rows:
                session_id = row.template_session_id or row.session_id

                try:
                    if cmd.dry_run:
                        await self._cancel.check_cancellable(row.occurrence_id)
                        dates_out.append(
                            ClosureDate(
                                occurrence_id=row.occurrence_id,
                                session_id=session_id,
                                start_at=row.start_at,
                                status="would_cancel",
                            )
                        )
                        continue
                    result = await self._cancel.execute(
                        CancelSessionOccurrenceCommand(
                            occurrence_id=row.occurrence_id,
                            reason=cmd.reason,
                            actor_id=cmd.actor_id,
                            notify=cmd.notify,
                            defer_family_notice=True,
                        )
                    )
                except DomainError as exc:
                    # Already cancelled, started, or inside a frozen payout
                    # period: the rest of the closure still goes ahead.
                    dates_out.append(_skipped(row, session_id, exc.message))
                    continue
                except Exception:
                    log.exception(
                        "enrollment.closure_date_failed",
                        extra={"occurrence_id": row.occurrence_id},
                    )
                    dates_out.append(_skipped(row, session_id, FAILED_RETRY))
                    continue
                dates_out.append(
                    ClosureDate(
                        occurrence_id=row.occurrence_id,
                        session_id=session_id,
                        start_at=row.start_at,
                        status="cancelled",
                        credits_issued=result.credits_issued,
                        billing_warning=result.billing_warning,
                    )
                )
                notices.append(
                    ClosedClassDate(
                        session_id=session_id,
                        start_at=row.start_at,
                        one_time_student_ids=result.one_time_student_ids,
                        credited_student_ids=result.credited_student_ids,
                        billing_warning=result.billing_warning,
                    )
                )
        finally:
            # Even if something above escapes, every date already cancelled
            # gets its family summary.
            notice = await self._notify(cmd, notices)

        return CloseAcademyDatesResult(
            dates=tuple(dates_out),
            cancelled=sum(1 for d in dates_out if d.status == "cancelled"),
            skipped=sum(1 for d in dates_out if d.status == "skipped"),
            credits_issued=sum(d.credits_issued for d in dates_out),
            families_affected=notice.families_affected,
            families_notified=notice.families_emailed,
            notice_failed=notice.failed,
        )

    async def _notify(
        self, cmd: CloseAcademyDatesCommand, notices: list[ClosedClassDate]
    ) -> ClosureNotice:
        if not (cmd.notify and notices and self._notifier is not None):
            return ClosureNotice()
        try:
            return await self._notifier.academy_closed(
                dates=notices, reason=cmd.reason, actor_id=cmd.actor_id
            )
        except Exception:
            log.exception("enrollment.academy_closure_notify_failed")
            return ClosureNotice(failed=True)


def _skipped(row: SessionOccurrence, session_id: str, reason: str) -> ClosureDate:
    return ClosureDate(
        occurrence_id=row.occurrence_id,
        session_id=session_id,
        start_at=row.start_at,
        status="skipped",
        skip_reason=reason,
    )
