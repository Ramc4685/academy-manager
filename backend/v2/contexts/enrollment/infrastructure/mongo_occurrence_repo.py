"""Mongo repository for durable session occurrences."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
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
            start_at=doc["start_at"],  # type: ignore[arg-type]
            end_at=doc["end_at"],  # type: ignore[arg-type]
            status=doc.get("status", "scheduled"),  # type: ignore[arg-type]
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
        start, end = _day_bounds_utc(on_date)
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


def _day_bounds_utc(on_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(on_date, time.min, tzinfo=UTC),
        datetime.combine(on_date, time.max, tzinfo=UTC),
    )


def _optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)
