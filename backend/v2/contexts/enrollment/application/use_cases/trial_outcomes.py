"""Came / Didn't come: the outcome of an approved trial (People CRM L3a).

People CRM spec §3.4 and the Pipeline card: "Came / Didn't come ... writes the
trial status ``completed``, which no code wrote before". ``MarkTrialOutcome``
is that one write. It is called from two places:

* the admin Inbox trial rows (``POST /admin/self-service/trials/{id}/outcome``),
  behind the same admin gate as approve and deny, and
* the coach Today roster (``POST /coach/trials/{id}/outcome``), where a coach
  may record it only for a trial whose assigned date belongs to a session they
  coach (``coach_id`` on the command). A coach asking about any other trial
  gets the same 404 as an unknown id, so the route never reveals that a trial
  exists on someone else's class.

Rules:

* Only an ``approved`` trial with an assigned, not-cancelled date takes an
  outcome, and not earlier than ``EARLY_MARK_WINDOW`` before that date's
  start (a coach marks arrivals as the class begins, not days ahead).
* A ``completed`` trial may be corrected (Came -> Didn't come and back);
  the same outcome again is a no-op that keeps the original author and time.
* ``converted`` (a registration followed), ``pending`` and ``denied`` refuse.
* The write is a compare-and-swap on the status, so a trial converted between
  the read and the write is never flipped back to ``completed``.

BILLING SAFETY: like the rest of the trial flow, this has no billing
dependency. ``LinkTrialConversion`` still treats ``completed`` as convertible.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import (
    TrialOutcome,
    TrialOutcomeNotAllowed,
    TrialRequest,
    TrialRequestNotFound,
)

#: How early before the class starts an outcome may be recorded.
EARLY_MARK_WINDOW = timedelta(hours=1)


class TrialOutcomeRepository(Protocol):
    async def get(self, request_id: str) -> TrialRequest | None: ...

    async def record_outcome(
        self, request_id: str, updates: dict[str, object]
    ) -> TrialRequest | None: ...


class TrialOccurrenceLookup(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...


class TrialCoachAssignments(Protocol):
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool: ...


class MarkTrialOutcomeCommand(BaseModel):
    model_config = {"frozen": True}

    request_id: str
    actor_id: str
    outcome: TrialOutcome
    #: Set for the coach surface: the trial's date must be on a session this
    #: coach coaches. ``None`` for staff (admin Inbox) and coach supervisors.
    coach_id: str | None = None


class MarkTrialOutcome:
    def __init__(
        self,
        *,
        trials: TrialOutcomeRepository,
        occurrences: TrialOccurrenceLookup,
        assignments: TrialCoachAssignments | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._trials = trials
        self._occurrences = occurrences
        self._assignments = assignments
        self._now = clock

    async def execute(self, cmd: MarkTrialOutcomeCommand) -> TrialRequest:
        request = await self._trials.get(cmd.request_id)
        if request is None:
            raise TrialRequestNotFound("trial request not found", request_id=cmd.request_id)

        occurrence = (
            await self._occurrences.get(request.assigned_occurrence_id)
            if request.assigned_occurrence_id
            else None
        )

        # Coach scope first, so a coach learns nothing (not even the status)
        # about a trial on a class they do not coach.
        if cmd.coach_id is not None:
            if (
                occurrence is None
                or self._assignments is None
                or not await self._assignments.is_coach_assigned(
                    cmd.coach_id, occurrence.session_id
                )
            ):
                raise TrialRequestNotFound("trial request not found", request_id=cmd.request_id)

        if request.status not in ("approved", "completed"):
            raise TrialOutcomeNotAllowed(
                "only an approved trial can be marked came or didn't come",
                request_id=cmd.request_id,
                reason=f"status_{request.status}",
            )
        if occurrence is None:
            raise TrialOutcomeNotAllowed(
                "the trial has no assigned date",
                request_id=cmd.request_id,
                reason="no_assigned_date",
            )
        if occurrence.status == "cancelled":
            raise TrialOutcomeNotAllowed(
                "the trial's class was cancelled",
                request_id=cmd.request_id,
                reason="date_cancelled",
            )
        now = self._now()
        if occurrence.start_at - EARLY_MARK_WINDOW > now:
            raise TrialOutcomeNotAllowed(
                "the trial's class has not started yet",
                request_id=cmd.request_id,
                reason="too_early",
            )

        if request.status == "completed" and request.outcome == cmd.outcome:
            return request  # same answer again: keep the original author and time

        updated = await self._trials.record_outcome(
            request.request_id,
            {
                "status": "completed",
                "outcome": cmd.outcome,
                "outcome_by": cmd.actor_id,
                "outcome_at": now,
            },
        )
        if updated is None:
            raise TrialOutcomeNotAllowed(
                "the trial changed while saving; reload and try again",
                request_id=cmd.request_id,
                reason="changed",
            )
        return updated
