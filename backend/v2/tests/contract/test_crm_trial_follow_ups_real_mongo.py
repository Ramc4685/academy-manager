"""Trial passed, no registration (roadmap L3c) on a real ``mongod``.

``real_db`` replays every migration, so the migration 0201 unique partial
index on ``(academy_id, source_key)`` is the production one. Against the
real repositories and the composition's adapters:

* the job creates ONE follow-up per trial marked Came 7+ days ago, and
  re-running it (or racing two runs) creates nothing more, even after staff
  marked the follow-up done;
* a family that registered after the trial (an application past draft, or
  a seat on the class for an existing child) gets none;
* per academy: academy B's run never sees academy A's trials, and the same
  trial id in two academies yields one follow-up in each;
* a follow-up a person adds (no ``source_key``) is untouched by the index.

Skipped without a ``mongod``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.v2.composition.trial_follow_ups import (
    MembershipOwnerLookup,
    MongoRegistrationCheck,
    TrialRequestPassedTrials,
)
from backend.v2.contexts.crm.application.use_cases.trial_follow_ups import (
    CreateTrialPassedFollowUps,
)
from backend.v2.contexts.crm.domain.family_notes import FamilyFollowUp
from backend.v2.contexts.crm.infrastructure.mongo_family_notes_repo import (
    MongoFamilyFollowUpRepository,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.tenancy import tenant_scope

A = "acad-l3c-a"
B = "acad-l3c-b"
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Family:
    family_id: str
    parent_name: str | None = None


class _Families:
    """Every parent is its own family (the family index is proved elsewhere)."""

    async def find(self, academy_id: str, family_id: str) -> _Family | None:
        return _Family(family_id)

    async def names(self, academy_id: str) -> dict[str, str | None]:
        return {}


async def _utc(_academy: str) -> str | None:
    return None


def _job(db: Any) -> CreateTrialPassedFollowUps:
    return CreateTrialPassedFollowUps(
        trials=TrialRequestPassedTrials(db),
        registrations=MongoRegistrationCheck(db),
        families=_Families(),
        owners=MembershipOwnerLookup(db),
        follow_ups=MongoFamilyFollowUpRepository(db),
        timezone=_utc,
        clock=lambda: NOW,
    )


def _trial(
    request_id: str,
    *,
    parent: str = "p-1",
    occurrence: str = "occ-1",
    outcome: str | None = "came",
    status: str = "completed",
    student_id: str | None = None,
) -> TrialRequest:
    return TrialRequest(
        request_id=request_id,
        academy_id="forged",  # the repository stamps the tenant
        parent_user_id=parent,
        student_ref="existing_student" if student_id else "prospective",
        student_id=student_id,
        prospective_child_name=None if student_id else "Sample Child",
        requested_session_id="s-1",
        preferred_start="2026-09-01",
        preferred_end="2026-09-30",
        status=status,  # type: ignore[arg-type]
        assigned_occurrence_id=occurrence,
        created_at=NOW - timedelta(days=20),
        outcome=outcome,  # type: ignore[arg-type]
        outcome_by="staff-1" if outcome else None,
        outcome_at=NOW - timedelta(days=9) if outcome else None,
    )


async def _seed_occurrence(db: Any, occurrence_id: str, days_ago: float, **kw: Any) -> None:
    start = NOW - timedelta(days=days_ago)
    await MongoSessionOccurrenceRepository(db).save_many(
        [
            SessionOccurrence(
                occurrence_id=occurrence_id,
                academy_id="forged",
                session_id="s-1",
                start_at=start,
                end_at=start + timedelta(hours=1),
                scheduled_coach_id="coach-1",
                **kw,
            )
        ]
    )


async def _seed_academy(db: Any, academy: str) -> None:
    with tenant_scope(academy):
        await _seed_occurrence(db, "occ-1", 9)
        await MongoTrialRequestRepository(db).add(_trial("tr-1"))
    await db["academy_memberships"].insert_one(
        {
            "membership_id": f"m-{academy}",
            "academy_id": academy,
            "user_id": f"owner-{academy}",
            "roles": ["owner"],
            "status": "active",
            "created_at": NOW - timedelta(days=400),
        }
    )


async def _rows(db: Any, academy: str) -> list[dict[str, Any]]:
    return [doc async for doc in db["family_follow_ups"].find({"academy_id": academy})]


async def test_one_follow_up_per_trial_and_reruns_create_nothing(real_db: Any) -> None:
    await _seed_academy(real_db, A)
    job = _job(real_db)
    with tenant_scope(A):
        first = await job.execute(academy_id=A)
    assert first.created == 1
    [row] = await _rows(real_db, A)
    assert row["source_key"] == "trial_passed:tr-1"
    assert row["parent_id"] == "p-1"
    assert row["assignee_user_id"] == f"owner-{A}"
    assert row["title"] == "Trial passed, no registration: Sample Child"
    assert row["due_on"] == "2026-09-24"
    assert row["status"] == "open"

    # Staff mark it done; the next day's run must not recreate it.
    with tenant_scope(A):
        repo = MongoFamilyFollowUpRepository(real_db)
        await repo.update("p-1", row["follow_up_id"], changes={"status": "done"})
        again = await job.execute(academy_id=A)
    assert (again.created, again.already_created) == (0, 1)
    assert len(await _rows(real_db, A)) == 1


async def test_concurrent_runs_insert_exactly_one(real_db: Any) -> None:
    await _seed_academy(real_db, A)

    async def run() -> int:
        with tenant_scope(A):
            return (await _job(real_db).execute(academy_id=A)).created

    results = await asyncio.gather(*(run() for _ in range(5)))
    assert sum(results) == 1
    assert len(await _rows(real_db, A)) == 1


async def test_per_academy_and_same_trial_id_in_two_academies(real_db: Any) -> None:
    await _seed_academy(real_db, A)
    with tenant_scope(B):
        assert (await _job(real_db).execute(academy_id=B)).candidates == 0
    assert await _rows(real_db, B) == []

    await _seed_academy(real_db, B)  # same trial id "tr-1" in academy B
    with tenant_scope(A):
        assert (await _job(real_db).execute(academy_id=A)).created == 1
    with tenant_scope(B):
        assert (await _job(real_db).execute(academy_id=B)).created == 1
    [row_a] = await _rows(real_db, A)
    [row_b] = await _rows(real_db, B)
    assert row_a["assignee_user_id"] == f"owner-{A}"
    assert row_b["assignee_user_id"] == f"owner-{B}"


async def test_no_op_when_the_family_registered_after_the_trial(real_db: Any) -> None:
    await _seed_academy(real_db, A)
    await real_db["onboarding_applications"].insert_one(
        {
            "application_id": "app-1",
            "academy_id": A,
            "parent_user_id": "p-1",
            "status": "PENDING_APPROVAL",
            "created_at": NOW - timedelta(days=3),
            "updated_at": NOW - timedelta(days=3),
        }
    )
    with tenant_scope(A):
        run = await _job(real_db).execute(academy_id=A)
    assert (run.created, run.registered) == (0, 1)
    assert await _rows(real_db, A) == []


async def test_draft_or_other_academy_application_is_not_a_registration(real_db: Any) -> None:
    await _seed_academy(real_db, A)
    await real_db["onboarding_applications"].insert_many(
        [
            {
                "application_id": "app-draft",
                "academy_id": A,
                "parent_user_id": "p-1",
                "status": "DRAFT",
                "created_at": NOW - timedelta(days=3),
            },
            {
                "application_id": "app-b",
                "academy_id": B,
                "parent_user_id": "p-1",
                "status": "APPROVED",
                "created_at": NOW - timedelta(days=3),
            },
            {
                "application_id": "app-old",
                "academy_id": A,
                "parent_user_id": "p-1",
                "status": "APPROVED",
                "created_at": NOW - timedelta(days=300),
                "updated_at": NOW - timedelta(days=299),
            },
        ]
    )
    with tenant_scope(A):
        assert (await _job(real_db).execute(academy_id=A)).created == 1


async def test_existing_child_with_a_seat_on_the_class_is_registered(real_db: Any) -> None:
    with tenant_scope(A):
        await _seed_occurrence(real_db, "occ-1", 9)
        await MongoTrialRequestRepository(real_db).add(_trial("tr-2", student_id="stu-1"))
    await real_db["enrollments"].insert_one(
        {
            "enrollment_id": "enr-1",
            "academy_id": A,
            "student_id": "stu-1",
            "session_id": "s-1",
            "status": "active",
        }
    )
    with tenant_scope(A):
        run = await _job(real_db).execute(academy_id=A)
    assert (run.created, run.registered) == (0, 1)


async def test_only_came_trials_whose_class_passed_seven_days_ago(real_db: Any) -> None:
    with tenant_scope(A):
        trials = MongoTrialRequestRepository(real_db)
        await _seed_occurrence(real_db, "occ-recent", 3)
        await _seed_occurrence(real_db, "occ-old", 9)
        await _seed_occurrence(real_db, "occ-stale", 90)
        await _seed_occurrence(real_db, "occ-cancelled", 9, status="cancelled")
        await trials.add(_trial("tr-recent", occurrence="occ-recent"))
        await trials.add(_trial("tr-noshow", occurrence="occ-old", outcome="no_show"))
        await trials.add(
            _trial("tr-approved", occurrence="occ-old", outcome=None, status="approved")
        )
        await trials.add(_trial("tr-converted", occurrence="occ-old", status="converted"))
        await trials.add(_trial("tr-stale", occurrence="occ-stale"))
        await trials.add(_trial("tr-cancelled", occurrence="occ-cancelled"))
        await trials.add(_trial("tr-due", occurrence="occ-old"))
        run = await _job(real_db).execute(academy_id=A)
    assert (run.candidates, run.created) == (1, 1)
    [row] = await _rows(real_db, A)
    assert row["source_key"] == "trial_passed:tr-due"
    # No owner in this academy: left unassigned.
    assert row["assignee_user_id"] == ""


async def test_manual_follow_ups_without_a_source_key_coexist(real_db: Any) -> None:
    with tenant_scope(A):
        repo = MongoFamilyFollowUpRepository(real_db)
        for n in range(2):
            await repo.add(
                FamilyFollowUp(
                    follow_up_id=f"manual-{n}",
                    academy_id=A,
                    parent_id="p-1",
                    title="Call back",
                    due_on=date(2026, 9, 25),
                    assignee_user_id="staff-1",
                    created_by="staff-1",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        rows = await repo.list_for_family("p-1")
    assert len(rows) == 2
    assert all(row.source_key is None for row in rows)
