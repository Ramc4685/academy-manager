"""In-memory stand-ins for the trial-outcome and pipeline-move stores (L3a).

They mirror the real repositories' semantics that the use cases rely on
(``feedback: test fakes must mirror real store semantics``):

* ``FakeTrialStore.record_outcome`` is a compare-and-swap on
  ``status in {approved, completed}`` exactly like
  ``MongoTrialRequestRepository.record_outcome``; a converted trial is left
  alone and ``None`` comes back.
* ``FakeContactStore.set_pipeline_override`` matches only while the stored
  override column equals ``expected_column`` (``None`` = no override) and the
  row is not ``enrolled``, like ``MongoCrmContactRepository``.
* Both are per-academy: rows of another academy are invisible.

The real behaviour is proven on a ``mongod`` in
``tests/contract/test_trial_outcome_pipeline_real_mongo.py``.
"""

from __future__ import annotations

from datetime import datetime

from backend.v2.contexts.crm.domain.models import CrmContact, PipelineOverride
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.shared.tenancy import current_academy_id


class FakeTrialStore:
    def __init__(self, *trials: TrialRequest) -> None:
        self.rows: dict[tuple[str, str], TrialRequest] = {
            (t.academy_id, t.request_id): t for t in trials
        }
        self.writes = 0

    async def get(self, request_id: str) -> TrialRequest | None:
        return self.rows.get((current_academy_id(), request_id))

    async def record_outcome(
        self, request_id: str, updates: dict[str, object]
    ) -> TrialRequest | None:
        key = (current_academy_id(), request_id)
        row = self.rows.get(key)
        if row is None or row.status not in ("approved", "completed"):
            return None
        updated = row.model_copy(update=updates)
        self.rows[key] = updated
        self.writes += 1
        return updated


class FakeOccurrences:
    def __init__(self, *occurrences: SessionOccurrence) -> None:
        self.rows = {(o.academy_id, o.occurrence_id): o for o in occurrences}

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        return self.rows.get((current_academy_id(), occurrence_id))


class FakeAssignments:
    """``{(coach_id, session_id)}`` pairs a coach coaches."""

    def __init__(self, *pairs: tuple[str, str]) -> None:
        self.pairs = set(pairs)

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return (coach_id, session_id) in self.pairs


class FakeContactStore:
    def __init__(self, *contacts: CrmContact) -> None:
        self.rows: dict[tuple[str, str], CrmContact] = {
            (c.academy_id, c.contact_id): c for c in contacts
        }
        self.writes = 0

    async def get(self, contact_id: str) -> CrmContact | None:
        return self.rows.get((current_academy_id(), contact_id))

    async def set_pipeline_override(
        self,
        contact_id: str,
        override: PipelineOverride,
        *,
        expected_column: str | None,
        updated_at: datetime,
    ) -> CrmContact | None:
        key = (current_academy_id(), contact_id)
        row = self.rows.get(key)
        if row is None or row.pipeline_status == "enrolled":
            return None
        stored = row.pipeline_override.column if row.pipeline_override else None
        if stored != expected_column:
            return None
        updated = row.model_copy(update={"pipeline_override": override, "updated_at": updated_at})
        self.rows[key] = updated
        self.writes += 1
        return updated
