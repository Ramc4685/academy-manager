"""Trial nudges (AI strategy Phase 1, item 3): templated, no model.

Two daily, academy-local jobs over ``trial_requests``, each sending one
email per trial at most once (``send_once`` over the ``trial_nudge_sends``
claim, the win-back pattern):

* ``SendTrialReminders`` (``send_trial_reminders``, 16:00 local): an
  ``approved`` trial whose assigned date is tomorrow on the academy's clock
  gets a reminder the afternoon before. A cancelled date is skipped; a trial
  reopened by a cancelled date comes back ``pending`` and is never reminded.
* ``SendTrialNoShowFollowUps`` (``send_trial_no_show_follow_ups``, 10:00
  local): a trial marked "Didn't come" gets one re-engagement email a few
  days later, unless the family has since booked another trial or
  registered (``linked_application_id``).

Both respect the academy's ``notifications.trial_nudges_enabled`` switch,
read with a default of on like win-back. The parent is a user, so the mail
goes through the ordinary gated user send path.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.shared.comms.claimed_send import SendClaimRepository, send_once
from backend.v2.shared.time import ensure_utc

#: A "Didn't come" is followed up after this long...
NO_SHOW_FOLLOW_UP_AFTER = timedelta(days=3)
#: ...and never for an outcome older than this (a job that was off for weeks
#: must not mail every no-show in history when it comes back).
NO_SHOW_LOOKBACK = timedelta(days=30)

TRIAL_REMINDER_KEY = "trial_reminder"
TRIAL_NO_SHOW_KEY = "trial_no_show"


class TrialSource(Protocol):
    async def list_by_status(self, status: str | None) -> list[TrialRequest]: ...

    async def list_for_parent(self, parent_user_id: str) -> list[TrialRequest]: ...


class TrialOccurrenceLookup(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...


class TrialNudgeSwitch(Protocol):
    async def is_enabled(self, academy_id: str) -> bool: ...


class TrialNudgeNotifier(Protocol):
    """Returns True when nothing is left to do (sent, or the recipient has
    opted out); False when the send should be retried on a later tick."""

    async def trial_reminder(self, *, trial: TrialRequest, local_start: datetime) -> bool: ...

    async def trial_no_show(self, *, trial: TrialRequest) -> bool: ...


class SendTrialReminders:
    def __init__(
        self,
        *,
        trials: TrialSource,
        occurrences: TrialOccurrenceLookup,
        send_repo: SendClaimRepository,
        notifier: TrialNudgeNotifier,
        switch: TrialNudgeSwitch,
    ) -> None:
        self._trials = trials
        self._occurrences = occurrences
        self._send_repo = send_repo
        self._notifier = notifier
        self._switch = switch

    async def execute(self, *, academy_id: str, local_now: datetime) -> int:
        """Run for ONE academy inside its tenant scope. ``local_now`` is on
        the academy's clock (``run_local_daily_job``), so "tomorrow" is the
        academy's tomorrow."""
        if not await self._switch.is_enabled(academy_id):
            return 0
        tomorrow = local_now.date() + timedelta(days=1)
        sent = 0
        for trial in await self._trials.list_by_status("approved"):
            if not trial.assigned_occurrence_id:
                continue
            occurrence = await self._occurrences.get(trial.assigned_occurrence_id)
            if occurrence is None or occurrence.status == "cancelled":
                continue
            local_start = ensure_utc(occurrence.start_at).astimezone(local_now.tzinfo)
            if local_start.date() != tomorrow:
                continue
            sent += await send_once(
                self._send_repo,
                academy_id=academy_id,
                subject_id=trial.request_id,
                nudge_key=TRIAL_REMINDER_KEY,
                send=partial(self._notifier.trial_reminder, trial=trial, local_start=local_start),
            )
        return sent


class SendTrialNoShowFollowUps:
    def __init__(
        self,
        *,
        trials: TrialSource,
        send_repo: SendClaimRepository,
        notifier: TrialNudgeNotifier,
        switch: TrialNudgeSwitch,
    ) -> None:
        self._trials = trials
        self._send_repo = send_repo
        self._notifier = notifier
        self._switch = switch

    async def execute(self, *, academy_id: str, local_now: datetime) -> int:
        if not await self._switch.is_enabled(academy_id):
            return 0
        sent = 0
        for trial in await self._trials.list_by_status("completed"):
            if (
                trial.outcome != "no_show"
                or trial.linked_application_id
                or trial.outcome_at is None
            ):
                continue
            marked_at = ensure_utc(trial.outcome_at)
            if not (
                local_now - NO_SHOW_LOOKBACK <= marked_at <= local_now - NO_SHOW_FOLLOW_UP_AFTER
            ):
                continue
            if await self._family_moved_on(trial):
                continue
            sent += await send_once(
                self._send_repo,
                academy_id=academy_id,
                subject_id=trial.request_id,
                nudge_key=TRIAL_NO_SHOW_KEY,
                send=partial(self._notifier.trial_no_show, trial=trial),
            )
        return sent

    async def _family_moved_on(self, trial: TrialRequest) -> bool:
        """A later trial request by the same parent that was not denied: the
        family already rebooked (or came, or registered), so no nudge."""
        created = ensure_utc(trial.created_at)
        return any(
            other.request_id != trial.request_id
            and other.status != "denied"
            and ensure_utc(other.created_at) > created
            for other in await self._trials.list_for_parent(trial.parent_user_id)
        )
