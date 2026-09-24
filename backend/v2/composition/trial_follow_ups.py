"""Composition for the "Trial passed, no registration" job (roadmap L3c).

Wiring only. The CRM context may not import enrollment, onboarding or
identity, so this module hands ``CreateTrialPassedFollowUps`` each owner's
read behind a CRM port:

* ``TrialRequestPassedTrials``: enrollment's trial requests marked Came and
  not converted, joined to the assigned occurrence's start (a cancelled date
  never counts);
* ``MongoRegistrationCheck``: onboarding applications past draft that the
  parent touched after requesting the trial, or (for an existing child) a
  non-terminal enrollment on the trial's class;
* ``MembershipOwnerLookup``: identity's active academy owner;
* the family directory the family record uses, and the follow-up repository
  (``add_once`` on the migration 0201 unique key).

Every read runs inside the job's ``tenant_scope``: the repositories stamp the
academy, and the two direct reads below filter ``academy_id`` explicitly.
Composed once at boot onto ``app.state.trial_follow_ups`` by ``main.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from backend.v2.composition.families_crm import family_directory
from backend.v2.contexts.crm.application.use_cases.trial_follow_ups import (
    CreateTrialPassedFollowUps,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_notes_repo import (
    MongoFamilyFollowUpRepository,
)
from backend.v2.contexts.enrollment.domain.models import NON_TERMINAL
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.time import ensure_utc
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

#: Application statuses that are NOT a registration: never submitted, or
#: given up before anyone reviewed it.
NOT_REGISTERED_APPLICATION_STATUSES = ("DRAFT", "CHECKOUT_EXPIRED", "ABANDONED")


@dataclass(frozen=True)
class _PassedTrial:
    trial_id: str
    parent_user_id: str
    student_id: str | None
    child_name: str | None
    session_id: str
    requested_at: datetime
    class_started_at: datetime


class TrialRequestPassedTrials:
    def __init__(self, db: Any) -> None:
        self._trials = MongoTrialRequestRepository(db)
        self._occurrences = MongoSessionOccurrenceRepository(db)

    async def came_not_converted(
        self, academy_id: str, *, started_after: datetime, started_before: datetime
    ) -> list[_PassedTrial]:
        out: list[_PassedTrial] = []
        for trial in await self._trials.list_by_status("completed"):
            if (
                trial.outcome != "came"
                or trial.linked_application_id
                or not trial.assigned_occurrence_id
            ):
                continue
            occurrence = await self._occurrences.get(trial.assigned_occurrence_id)
            if occurrence is None or occurrence.status == "cancelled":
                continue
            started = ensure_utc(occurrence.start_at)
            if not (started_after <= started <= started_before):
                continue
            out.append(
                _PassedTrial(
                    trial_id=trial.request_id,
                    parent_user_id=trial.parent_user_id,
                    student_id=trial.student_id,
                    child_name=trial.prospective_child_name,
                    session_id=trial.requested_session_id,
                    requested_at=ensure_utc(trial.created_at),
                    class_started_at=started,
                )
            )
        return out


class MongoRegistrationCheck:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def registered_since(
        self,
        academy_id: str,
        *,
        parent_user_id: str,
        student_id: str | None,
        session_id: str,
        since: datetime,
    ) -> bool:
        cursor = self._db["onboarding_applications"].find(
            {
                "academy_id": academy_id,
                "parent_user_id": parent_user_id,
                "status": {"$nin": list(NOT_REGISTERED_APPLICATION_STATUSES)},
            },
            {"created_at": 1, "updated_at": 1},
        )
        async for doc in cursor:
            touched = doc.get("updated_at") or doc.get("created_at")
            if isinstance(touched, datetime) and ensure_utc(touched) >= since:
                return True
        if student_id:
            seat = await self._db["enrollments"].find_one(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                    "session_id": session_id,
                    "status": {"$in": sorted(NON_TERMINAL)},
                },
                {"_id": 1},
            )
            if seat is not None:
                return True
        return False


class MembershipOwnerLookup:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def owner_user_id(self, academy_id: str) -> str | None:
        cursor = (
            self._db["academy_memberships"]
            .find(
                # A row with no status reads as active (the membership repo's default).
                {"academy_id": academy_id, "roles": "owner", "status": {"$in": ["active", None]}},
                {"user_id": 1},
            )
            .sort([("created_at", 1), ("_id", 1)])
            .limit(1)
        )
        async for doc in cursor:
            return cast(str, doc["user_id"]) if doc.get("user_id") else None
        return None


def compose_trial_follow_ups(db: Any) -> CreateTrialPassedFollowUps:
    return CreateTrialPassedFollowUps(
        trials=TrialRequestPassedTrials(db),
        registrations=MongoRegistrationCheck(db),
        families=family_directory(db),
        owners=MembershipOwnerLookup(db),
        follow_ups=MongoFamilyFollowUpRepository(db),
        timezone=academy_timezone_lookup(db),
    )
