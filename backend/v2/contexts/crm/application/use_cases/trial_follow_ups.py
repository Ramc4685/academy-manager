"""Trial passed, no registration: the automatic follow-up (roadmap L3c).

A scheduled job (``create_trial_follow_ups`` in ``main.py``, daily, per
academy) runs ``CreateTrialPassedFollowUps``. For every trial of the academy
that was marked **Came** and that no registration has converted, whose class
started at least ``FOLLOW_UP_AFTER`` (7 days) ago, it adds ONE family
follow-up "Trial passed, no registration" to the family's record and the
Follow-ups queue:

* keyed on the trial: ``source_key = "trial_passed:<trial id>"``, unique per
  academy (migration 0201). Running the job again, on another machine, or
  after staff marked the follow-up done never creates a second one;
* no-op when the family did register after requesting the trial (an
  application past draft, or a seat on the class for an existing child);
* assigned to the academy's owner, or left unassigned when there is none;
* due on the academy's local today (so it lands in the Today bucket);
* ``created_by = SYSTEM_ACTOR`` so the record says a job wrote it.

A trial whose class is older than ``LOOKBACK`` is left alone: a Came marked
months late (or a job that was off for weeks) should not flood the queue with
stale families. A parent the family index does not know (for example a
removed account) is skipped, never guessed.

No email, no money: this only writes a to-do for staff.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.v2.contexts.crm.application.ports import (
    AcademyOwnerLookup,
    FamilyDirectory,
    PassedTrial,
    PassedTrialSource,
    RegistrationCheck,
    SourcedFollowUpWriter,
)
from backend.v2.contexts.crm.application.use_cases.family_follow_ups import (
    AcademyTimezone,
    academy_today,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import utc_now_ms
from backend.v2.contexts.crm.domain.family_notes import (
    MAX_FOLLOW_UP_TITLE_LEN,
    TRIAL_PASSED_FOLLOW_UP_TITLE,
    UNASSIGNED,
    FamilyFollowUp,
    normalize_follow_up_title,
    trial_passed_source_key,
)
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

#: The trial's class must have started at least this long ago.
FOLLOW_UP_AFTER = timedelta(days=7)
#: ...and not longer ago than this.
LOOKBACK = timedelta(days=60)
#: ``created_by`` of a job-written follow-up.
SYSTEM_ACTOR = "system:trial_follow_up"


@dataclass(frozen=True)
class TrialFollowUpRun:
    candidates: int = 0
    created: int = 0
    already_created: int = 0
    registered: int = 0
    unknown_family: int = 0


def follow_up_title(trial: PassedTrial) -> str:
    child = (trial.child_name or "").strip()
    if not child:
        return TRIAL_PASSED_FOLLOW_UP_TITLE
    title = f"{TRIAL_PASSED_FOLLOW_UP_TITLE}: {child}"
    if len(title) > MAX_FOLLOW_UP_TITLE_LEN:
        return TRIAL_PASSED_FOLLOW_UP_TITLE
    return normalize_follow_up_title(title)


class CreateTrialPassedFollowUps:
    def __init__(
        self,
        *,
        trials: PassedTrialSource,
        registrations: RegistrationCheck,
        families: FamilyDirectory,
        owners: AcademyOwnerLookup,
        follow_ups: SourcedFollowUpWriter,
        timezone: AcademyTimezone,
        clock: Callable[[], datetime] = utc_now_ms,
        new_id: Callable[[], str] = new_ulid,
    ) -> None:
        self._trials = trials
        self._registrations = registrations
        self._families = families
        self._owners = owners
        self._follow_ups = follow_ups
        self._timezone = timezone
        self._clock = clock
        self._new_id = new_id

    async def execute(self, *, academy_id: str) -> TrialFollowUpRun:
        """Run for ONE academy. The caller holds the academy's tenant scope."""
        now = self._clock()
        trials = await self._trials.came_not_converted(
            academy_id,
            started_after=now - LOOKBACK,
            started_before=now - FOLLOW_UP_AFTER,
        )
        created = already = registered = unknown = 0
        owner: str | None = None
        owner_looked_up = False
        today = None
        for trial in trials:
            if await self._registrations.registered_since(
                academy_id,
                parent_user_id=trial.parent_user_id,
                student_id=trial.student_id,
                session_id=trial.session_id,
                since=trial.requested_at,
            ):
                registered += 1
                continue
            family = await self._families.find(academy_id, trial.parent_user_id)
            if family is None:
                unknown += 1
                log.info(
                    "trial_follow_up_family_unknown",
                    extra={"academy_id": academy_id, "trial_id": trial.trial_id},
                )
                continue
            if not owner_looked_up:
                owner = await self._owners.owner_user_id(academy_id)
                owner_looked_up = True
            if today is None:
                today = await academy_today(self._timezone, academy_id, now)
            inserted = await self._follow_ups.add_once(
                FamilyFollowUp(
                    follow_up_id=self._new_id(),
                    academy_id=academy_id,
                    parent_id=family.family_id,
                    title=follow_up_title(trial),
                    due_on=today,
                    assignee_user_id=owner or UNASSIGNED,
                    status="open",
                    created_by=SYSTEM_ACTOR,
                    created_at=now,
                    updated_at=now,
                    source_key=trial_passed_source_key(trial.trial_id),
                )
            )
            if inserted:
                created += 1
            else:
                already += 1
        return TrialFollowUpRun(
            candidates=len(trials),
            created=created,
            already_created=already,
            registered=registered,
            unknown_family=unknown,
        )
