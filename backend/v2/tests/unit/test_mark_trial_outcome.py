"""MarkTrialOutcome (People CRM L3a): Came / Didn't come on an approved trial.

Against ``tests/fixtures/trial_outcome_fakes.py``, whose store mirrors the
real compare-and-swap (proven on ``mongod`` in
``contract/test_trial_outcome_pipeline_real_mongo.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.trial_outcome_fakes import (
    FakeAssignments,
    FakeOccurrences,
    FakeTrialStore,
)

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 9, 24, 18, 30, tzinfo=UTC)
CLASS_START = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)


def _trial(request_id: str = "tr-1", *, academy: str = A, **kw: object) -> TrialRequest:
    base: dict[str, object] = {
        "request_id": request_id,
        "academy_id": academy,
        "parent_user_id": "p-1",
        "student_ref": "prospective",
        "prospective_child_name": "Sample Child",
        "requested_session_id": "s-1",
        "preferred_start": "2026-09-20",
        "preferred_end": "2026-09-30",
        "status": "approved",
        "assigned_occurrence_id": "occ-1",
        "created_at": NOW - timedelta(days=3),
    }
    base.update(kw)
    return TrialRequest(**base)  # type: ignore[arg-type]


def _occ(
    occurrence_id: str = "occ-1",
    *,
    academy: str = A,
    start: datetime = CLASS_START,
    status: str = "scheduled",
) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id=academy,
        session_id="s-1",
        start_at=start,
        end_at=start + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        scheduled_coach_id="coach-1",
    )


def _use_case(
    trials: FakeTrialStore, occurrences: FakeOccurrences | None = None, *, now: datetime = NOW
) -> MarkTrialOutcome:
    return MarkTrialOutcome(
        trials=trials,
        occurrences=occurrences or FakeOccurrences(_occ()),
        assignments=FakeAssignments(("coach-1", "s-1")),
        clock=lambda: now,
    )


def _cmd(outcome: str = "came", **kw: object) -> MarkTrialOutcomeCommand:
    return MarkTrialOutcomeCommand(
        request_id=str(kw.pop("request_id", "tr-1")),
        actor_id=str(kw.pop("actor_id", "staff-1")),
        outcome=outcome,  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


async def test_came_completes_the_trial_with_author_and_time() -> None:
    store = FakeTrialStore(_trial())
    with tenant_scope(A):
        result = await _use_case(store).execute(_cmd("came"))
    assert result.status == "completed"
    assert (result.outcome, result.outcome_by, result.outcome_at) == ("came", "staff-1", NOW)


async def test_didnt_come_is_recorded_as_no_show() -> None:
    store = FakeTrialStore(_trial())
    with tenant_scope(A):
        result = await _use_case(store).execute(_cmd("no_show"))
    assert (result.status, result.outcome) == ("completed", "no_show")


async def test_same_outcome_again_is_a_no_op_keeping_the_first_author() -> None:
    store = FakeTrialStore(_trial())
    with tenant_scope(A):
        await _use_case(store).execute(_cmd("came", actor_id="staff-1"))
        again = await _use_case(store, now=NOW + timedelta(minutes=5)).execute(
            _cmd("came", actor_id="staff-2")
        )
    assert (again.outcome_by, again.outcome_at) == ("staff-1", NOW)
    assert store.writes == 1


async def test_a_completed_trial_can_be_corrected() -> None:
    store = FakeTrialStore(_trial())
    with tenant_scope(A):
        await _use_case(store).execute(_cmd("came"))
        fixed = await _use_case(store).execute(_cmd("no_show", actor_id="staff-2"))
    assert (fixed.status, fixed.outcome, fixed.outcome_by) == ("completed", "no_show", "staff-2")


@pytest.mark.parametrize("status", ["pending", "denied", "converted"])
async def test_only_approved_or_completed_trials_take_an_outcome(status: str) -> None:
    store = FakeTrialStore(_trial(status=status))
    with tenant_scope(A), pytest.raises(TrialOutcomeNotAllowed) as err:
        await _use_case(store).execute(_cmd())
    assert err.value.details["reason"] == f"status_{status}"
    assert store.writes == 0


async def test_refuses_without_an_assigned_date() -> None:
    store = FakeTrialStore(_trial(assigned_occurrence_id=None))
    with tenant_scope(A), pytest.raises(TrialOutcomeNotAllowed) as err:
        await _use_case(store).execute(_cmd())
    assert err.value.details["reason"] == "no_assigned_date"


async def test_refuses_a_cancelled_date() -> None:
    store = FakeTrialStore(_trial())
    with tenant_scope(A), pytest.raises(TrialOutcomeNotAllowed) as err:
        await _use_case(store, FakeOccurrences(_occ(status="cancelled"))).execute(_cmd())
    assert err.value.details["reason"] == "date_cancelled"


async def test_refuses_more_than_an_hour_before_the_class() -> None:
    store = FakeTrialStore(_trial())
    early = CLASS_START - timedelta(hours=1, minutes=1)
    with tenant_scope(A), pytest.raises(TrialOutcomeNotAllowed) as err:
        await _use_case(store, now=early).execute(_cmd())
    assert err.value.details["reason"] == "too_early"
    # Within the hour before start is fine (arrivals are marked as class begins).
    with tenant_scope(A):
        ok = await _use_case(store, now=CLASS_START - timedelta(minutes=30)).execute(_cmd())
    assert ok.status == "completed"


async def test_unknown_or_other_academy_trial_is_not_found() -> None:
    store = FakeTrialStore(_trial(academy=B))
    with tenant_scope(A), pytest.raises(TrialRequestNotFound):
        await _use_case(store).execute(_cmd())
    assert store.writes == 0


async def test_coach_may_mark_only_trials_on_sessions_they_coach() -> None:
    store = FakeTrialStore(_trial())
    with tenant_scope(A):
        ok = await _use_case(store).execute(_cmd("came", coach_id="coach-1"))
    assert ok.outcome == "came"

    store = FakeTrialStore(_trial())
    with tenant_scope(A), pytest.raises(TrialRequestNotFound):
        await _use_case(store).execute(_cmd("came", coach_id="coach-other"))
    assert store.writes == 0


async def test_coach_learns_nothing_about_other_classes_trials() -> None:
    """A denied trial on someone else's class is a 404 for the coach, not the
    409 that would reveal it exists."""
    store = FakeTrialStore(_trial(status="denied"))
    with tenant_scope(A), pytest.raises(TrialRequestNotFound):
        await _use_case(store).execute(_cmd("came", coach_id="coach-other"))
    store = FakeTrialStore(_trial(assigned_occurrence_id=None, status="pending"))
    with tenant_scope(A), pytest.raises(TrialRequestNotFound):
        await _use_case(store).execute(_cmd("came", coach_id="coach-1"))


async def test_a_trial_converted_while_saving_is_not_flipped_back() -> None:
    """The store's status CAS decides: converted between read and write."""

    class _ConvertsOnRead(FakeTrialStore):
        async def get(self, request_id: str) -> TrialRequest | None:
            row = await super().get(request_id)
            key = (A, request_id)
            self.rows[key] = self.rows[key].model_copy(update={"status": "converted"})
            return row

    store = _ConvertsOnRead(_trial())
    with tenant_scope(A), pytest.raises(TrialOutcomeNotAllowed) as err:
        await _use_case(store).execute(_cmd())
    assert err.value.details["reason"] == "changed"
    assert store.rows[(A, "tr-1")].status == "converted"
