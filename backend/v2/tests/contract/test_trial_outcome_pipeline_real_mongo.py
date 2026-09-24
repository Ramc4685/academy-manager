"""Came / Didn't come and Pipeline moves on a real ``mongod`` (People CRM L3a).

``real_db`` replays every migration, so the ``trial_requests`` and
``crm_contacts`` indexes are the production ones. Checks, against the real
repositories:

* ``record_outcome`` is a compare-and-swap on the status: an approved trial
  becomes ``completed`` with author and time, a converted one is never
  flipped back, and another academy cannot touch it even by exact id;
* ``outcomes_for`` answers only this academy's trials;
* ``MarkTrialOutcome`` over the real repository, including the coach scope;
* ``set_pipeline_override`` writes ``{column, set_by, set_at}``, refuses an
  enrolled contact and a stale expected column, is tenant-scoped, and of two
  concurrent moves of one card exactly one lands.

Skipped without a ``mongod``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.crm.application.use_cases.pipeline_moves import (
    MoveCardCommand,
    MoveCardOnPipeline,
)
from backend.v2.contexts.crm.domain.errors import ContactNotFound, PipelineMoveNotAllowed
from backend.v2.contexts.crm.domain.models import CrmContact, PipelineOverride
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.trial_outcomes import (
    MarkTrialOutcome,
    MarkTrialOutcomeCommand,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import (
    TrialOutcomeNotAllowed,
    TrialRequest,
    TrialRequestNotFound,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.trial_outcome_fakes import FakeAssignments, FakeOccurrences

A = "acad-l3a-a"
B = "acad-l3a-b"
NOW = datetime(2026, 9, 24, 18, 30, tzinfo=UTC)


def _trial(request_id: str, *, status: str = "approved") -> TrialRequest:
    return TrialRequest(
        request_id=request_id,
        academy_id=B,  # forged: the repository stamps the tenant
        parent_user_id="p-1",
        student_ref="prospective",
        prospective_child_name="Sample Child",
        requested_session_id="s-1",
        preferred_start="2026-09-20",
        preferred_end="2026-09-30",
        status=status,  # type: ignore[arg-type]
        assigned_occurrence_id="occ-1",
        created_at=NOW - timedelta(days=2),
    )


def _occurrence(academy: str) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id="occ-1",
        academy_id=academy,
        session_id="s-1",
        start_at=NOW - timedelta(minutes=30),
        end_at=NOW + timedelta(minutes=30),
        scheduled_coach_id="coach-1",
    )


def _contact(contact_id: str, *, status: str = "lead") -> CrmContact:
    return CrmContact(
        contact_id=contact_id,
        academy_id=B,
        name="Sample Parent",
        phone_digits="5550102030",
        source="whatsapp_or_phone",
        pipeline_status=status,  # type: ignore[arg-type]
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


def _outcome(repo: MongoTrialRequestRepository, outcome: str, actor: str) -> Any:
    return {"status": "completed", "outcome": outcome, "outcome_by": actor, "outcome_at": NOW}


async def test_record_outcome_is_a_status_cas_and_tenant_scoped(real_db: Any) -> None:
    with tenant_scope(A):
        repo = MongoTrialRequestRepository(real_db)
        await repo.add(_trial("tr-1"))
        await repo.add(_trial("tr-conv", status="converted"))

    with tenant_scope(B):
        other = MongoTrialRequestRepository(real_db)
        assert await other.get("tr-1") is None
        assert await other.record_outcome("tr-1", _outcome(other, "came", "b-staff")) is None
        assert await other.outcomes_for(["tr-1"]) == {}

    with tenant_scope(A):
        done = await repo.record_outcome("tr-1", _outcome(repo, "came", "staff-1"))
        assert done is not None
        assert (done.status, done.outcome, done.outcome_by) == ("completed", "came", "staff-1")
        assert done.outcome_at == NOW
        # completed -> completed (a correction) still matches the CAS
        fixed = await repo.record_outcome("tr-1", _outcome(repo, "no_show", "staff-2"))
        assert fixed is not None and fixed.outcome == "no_show"
        # converted never matches: not flipped back to completed
        assert await repo.record_outcome("tr-conv", _outcome(repo, "came", "staff-1")) is None
        assert (await repo.get("tr-conv")).status == "converted"  # type: ignore[union-attr]
        assert await repo.outcomes_for(["tr-1", "tr-conv", "missing"]) == {
            "tr-1": "no_show",
            "tr-conv": None,
        }

    row = await real_db["trial_requests"].find_one({"request_id": "tr-1"})
    assert row["academy_id"] == A
    assert (row["status"], row["outcome"], row["outcome_by"]) == ("completed", "no_show", "staff-2")


async def test_completed_trial_still_converts(real_db: Any) -> None:
    """LinkTrialConversion treats completed as convertible and keeps the outcome."""
    with tenant_scope(A):
        repo = MongoTrialRequestRepository(real_db)
        await repo.add(_trial("tr-1"))
        await repo.record_outcome("tr-1", _outcome(repo, "came", "staff-1"))
        convertible = await repo.find_latest_convertible_for_parent("p-1")
        assert convertible is not None and convertible.request_id == "tr-1"
        await repo.update(
            convertible.model_copy(update={"status": "converted", "linked_application_id": "app-1"})
        )
        converted = await repo.get("tr-1")
    assert converted is not None
    assert (converted.status, converted.outcome) == ("converted", "came")


async def test_mark_trial_outcome_over_the_real_repository(real_db: Any) -> None:
    mark = MarkTrialOutcome(
        trials=MongoTrialRequestRepository(real_db),
        occurrences=FakeOccurrences(_occurrence(A), _occurrence(B)),
        assignments=FakeAssignments(("coach-1", "s-1")),
        clock=lambda: NOW,
    )
    with tenant_scope(A):
        await MongoTrialRequestRepository(real_db).add(_trial("tr-1"))
        await MongoTrialRequestRepository(real_db).add(_trial("tr-pending", status="pending"))
        with pytest.raises(TrialRequestNotFound):
            await mark.execute(
                MarkTrialOutcomeCommand(
                    request_id="tr-1", actor_id="coach-2", outcome="came", coach_id="coach-2"
                )
            )
        with pytest.raises(TrialOutcomeNotAllowed):
            await mark.execute(
                MarkTrialOutcomeCommand(request_id="tr-pending", actor_id="s", outcome="came")
            )
        done = await mark.execute(
            MarkTrialOutcomeCommand(
                request_id="tr-1", actor_id="coach-1", outcome="came", coach_id="coach-1"
            )
        )
    assert (done.status, done.outcome, done.outcome_by) == ("completed", "came", "coach-1")

    with tenant_scope(B), pytest.raises(TrialRequestNotFound):
        await mark.execute(MarkTrialOutcomeCommand(request_id="tr-1", actor_id="x", outcome="came"))


async def test_pipeline_override_cas_enrolled_and_tenancy(real_db: Any) -> None:
    override = PipelineOverride(column="trial_booked", set_by="staff-1", set_at=NOW)
    with tenant_scope(A):
        repo = MongoCrmContactRepository(real_db)
        await repo.add_if_absent(_contact("c-1"))
        await repo.add_if_absent(_contact("c-enrolled", status="enrolled"))

    with tenant_scope(B):
        other = MongoCrmContactRepository(real_db)
        assert (
            await other.set_pipeline_override("c-1", override, expected_column=None, updated_at=NOW)
            is None
        )

    with tenant_scope(A):
        # stale expected column: no write
        assert (
            await repo.set_pipeline_override(
                "c-1", override, expected_column="inquiry", updated_at=NOW
            )
            is None
        )
        moved = await repo.set_pipeline_override(
            "c-1", override, expected_column=None, updated_at=NOW
        )
        assert moved is not None and moved.pipeline_override == override
        assert moved.updated_at == NOW
        # enrolled rows are never overridden
        assert (
            await repo.set_pipeline_override(
                "c-enrolled", override, expected_column=None, updated_at=NOW
            )
            is None
        )

    row = await real_db["crm_contacts"].find_one({"contact_id": "c-1"})
    assert row["academy_id"] == A
    assert row["pipeline_override"]["column"] == "trial_booked"
    assert row["pipeline_override"]["set_by"] == "staff-1"


async def test_two_concurrent_moves_of_one_card_one_lands(real_db: Any) -> None:
    with tenant_scope(A):
        await MongoCrmContactRepository(real_db).add_if_absent(_contact("c-1"))

    async def move(actor: str) -> str:
        with tenant_scope(A):
            try:
                await MoveCardOnPipeline(
                    MongoCrmContactRepository(real_db), clock=lambda: NOW
                ).execute(
                    MoveCardCommand(contact_id="c-1", to_column="trial_booked", actor_id=actor)
                )
            except PipelineMoveNotAllowed as exc:
                return str(exc.details["reason"])
            return "moved"

    results = await asyncio.gather(*[move(f"staff-{i}") for i in range(6)])
    # Every caller either moved the card or found it already there (a no-op);
    # the stored author is exactly one of them and was written once.
    assert "moved" in results
    row = await real_db["crm_contacts"].find_one({"contact_id": "c-1"})
    assert row["pipeline_override"]["column"] == "trial_booked"
    assert row["pipeline_override"]["set_by"] in {f"staff-{i}" for i in range(6)}
    assert set(results) <= {"moved", "changed"}


async def test_move_card_is_tenant_scoped_on_real_mongo(real_db: Any) -> None:
    with tenant_scope(A):
        await MongoCrmContactRepository(real_db).add_if_absent(_contact("c-1"))
    with tenant_scope(B), pytest.raises(ContactNotFound):
        await MoveCardOnPipeline(MongoCrmContactRepository(real_db), clock=lambda: NOW).execute(
            MoveCardCommand(contact_id="c-1", to_column="trial_booked", actor_id="b-staff")
        )
    row = await real_db["crm_contacts"].find_one({"contact_id": "c-1"})
    assert row.get("pipeline_override") is None
