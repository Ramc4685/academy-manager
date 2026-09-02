"""Mongo repository for durable session occurrences."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSessionOccurrenceRepository(TenantScopedRepository):
    collection_name = "session_occurrences"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> SessionOccurrence:
        return SessionOccurrence(
            occurrence_id=str(doc["occurrence_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            start_at=doc["start_at"],
            end_at=doc["end_at"],
            status=doc.get("status", "scheduled"),
            scheduled_coach_id=str(doc["scheduled_coach_id"]),
            actual_coach_id=_optional_str(doc.get("actual_coach_id")),
            substitute_coach_id=_optional_str(doc.get("substitute_coach_id")),
            is_billable=bool(doc.get("is_billable", True)),
            is_payable=bool(doc.get("is_payable", True)),
            cancellation_reason=_optional_str(doc.get("cancellation_reason")),
            template_session_id=_optional_str(doc.get("template_session_id")),
        )

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        doc = await self._find_one({"occurrence_id": occurrence_id})
        return self._to_domain(doc) if doc else None

    async def list_for_session(self, session_id: str) -> list[SessionOccurrence]:
        cursor = self._find_many(
            {
                "$or": [
                    {"session_id": session_id},
                    {"template_session_id": session_id},
                ]
            },
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_coach_on_date(
        self,
        *,
        coach_id: str,
        on_date: date,
    ) -> list[SessionOccurrence]:
        # Occurrences are stored as UTC instants but belong to a session-local
        # calendar day. Fetch a widened UTC window (±1 day) so evening classes
        # whose UTC instant rolls past midnight are still candidates; the
        # application layer (ListCoachOccurrencesForDate) narrows the result
        # to the requested date in each session's own timezone (#510).
        start, end = _candidate_day_bounds_utc(on_date)
        cursor = self._find_many(
            {
                "start_at": {"$gte": start, "$lte": end},
                "status": {"$ne": "cancelled"},
                "$or": [
                    {"scheduled_coach_id": coach_id},
                    {"actual_coach_id": coach_id},
                    {"substitute_coach_id": coach_id},
                ],
            },
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_coach_upcoming(
        self,
        *,
        coach_id: str,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[SessionOccurrence]:
        start_at = now or datetime.now(UTC)
        cursor = self._find_many(
            {
                "start_at": {"$gte": start_at},
                "status": {"$ne": "cancelled"},
                "$or": [
                    {"scheduled_coach_id": coach_id},
                    {"actual_coach_id": coach_id},
                    {"substitute_coach_id": coach_id},
                ],
            },
            sort=[("start_at", 1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_on_date(self, *, on_date: date) -> list[SessionOccurrence]:
        """Every non-cancelled occurrence in the academy on ``on_date``.

        Coach-supervisor counterpart of ``list_for_coach_on_date``: same
        widened UTC candidate window (#510), no coach filter. Tenant scope
        comes from ``_find_many`` like every other read here.
        """
        start, end = _candidate_day_bounds_utc(on_date)
        cursor = self._find_many(
            {
                "start_at": {"$gte": start, "$lte": end},
                "status": {"$ne": "cancelled"},
            },
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_upcoming(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[SessionOccurrence]:
        """Upcoming non-cancelled occurrences across the academy."""
        start_at = now or datetime.now(UTC)
        cursor = self._find_many(
            {
                "start_at": {"$gte": start_at},
                "status": {"$ne": "cancelled"},
            },
            sort=[("start_at", 1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_session_between(
        self,
        *,
        session_id: str,
        start_at,
        end_at,
    ) -> list[SessionOccurrence]:
        cursor = self._find_many(
            {
                "$or": [
                    {"session_id": session_id},
                    {"template_session_id": session_id},
                ],
                "start_at": {"$gte": start_at, "$lte": end_at},
            },
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def next_upcoming_start_for_session(
        self,
        session_id: str,
        *,
        now: datetime,
    ) -> datetime | None:
        """The start time of the next scheduled occurrence for this session
        at/after ``now``, or ``None`` if there isn't one. Used by self-cancel
        (R4) to judge notice met/not-met against the policy's minimum notice
        window."""
        doc = await self._find_one_in_collection(
            self.collection_name,
            {
                "$or": [
                    {"session_id": session_id},
                    {"template_session_id": session_id},
                ],
                "status": "scheduled",
                "start_at": {"$gte": now},
            },
            sort=[("start_at", 1)],
        )
        if doc is None:
            return None
        return doc["start_at"]

    async def list_upcoming_scheduled_between(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SessionOccurrence]:
        """Scheduled occurrences starting in [start_at, end_at] — used by
        makeup-eligibility (Task 4) to find candidate targets within the
        policy's expiry window."""
        cursor = self._find_many(
            {
                "status": "scheduled",
                "start_at": {"$gte": start_at, "$lte": end_at},
            },
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def save_many(self, occurrences: list[SessionOccurrence]) -> None:
        for occurrence in occurrences:
            try:
                await self._insert_one(_to_doc(occurrence))
            except DuplicateKeyError:
                continue

    async def update_coach_assignment(
        self,
        *,
        occurrence_id: str,
        actual_coach_id: str | None = None,
        substitute_coach_id: str | None = None,
        assignment_reason: str | None = None,
    ) -> SessionOccurrence | None:
        update_fields: dict[str, Any] = {
            "updated_at": datetime.now(UTC),
        }
        if actual_coach_id is not None:
            update_fields["actual_coach_id"] = actual_coach_id
        if substitute_coach_id is not None:
            update_fields["substitute_coach_id"] = substitute_coach_id
        if assignment_reason is not None:
            update_fields["coach_assignment_reason"] = assignment_reason

        await self._update_one(
            {"occurrence_id": occurrence_id},
            {"$set": update_fields},
        )
        return await self.get(occurrence_id)


def _to_doc(occurrence: SessionOccurrence) -> dict[str, Any]:
    return {
        "occurrence_id": occurrence.occurrence_id,
        "session_id": occurrence.session_id,
        "start_at": occurrence.start_at,
        "end_at": occurrence.end_at,
        "status": occurrence.status,
        "scheduled_coach_id": occurrence.scheduled_coach_id,
        "actual_coach_id": occurrence.actual_coach_id,
        "substitute_coach_id": occurrence.substitute_coach_id,
        "is_billable": occurrence.is_billable,
        "is_payable": occurrence.is_payable,
        "cancellation_reason": occurrence.cancellation_reason,
        "template_session_id": occurrence.template_session_id,
    }


def _candidate_day_bounds_utc(on_date: date) -> tuple[datetime, datetime]:
    """UTC window guaranteed to contain every instant that falls on
    ``on_date`` in ANY timezone (offsets span UTC-12..UTC+14, so ±1 day
    around the UTC day covers them all). Callers must re-filter by the
    session-local date."""
    return (
        datetime.combine(on_date - timedelta(days=1), time.min, tzinfo=UTC),
        datetime.combine(on_date + timedelta(days=1), time.max, tzinfo=UTC),
    )


def _optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)
