"""Mongo repository for one-time occurrence roster entries.

Written when a makeup (Task 5) or trial (Task 7) request is approved — the
student attends exactly one occurrence without a standing enrollment. Task
3 defines the repository; later tasks are the writers.
"""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoOccurrenceRosterRepository(TenantScopedRepository):
    collection_name = "occurrence_roster_entries"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> OccurrenceRosterEntry:
        return OccurrenceRosterEntry(
            entry_id=str(doc["entry_id"]),
            academy_id=str(doc["academy_id"]),
            occurrence_id=str(doc["occurrence_id"]),
            student_id=str(doc["student_id"]),
            source=doc["source"],
            origin_request_id=str(doc["origin_request_id"]),
            created_at=doc["created_at"],
        )

    @staticmethod
    def _to_doc(entry: OccurrenceRosterEntry) -> dict[str, object]:
        return {
            "entry_id": entry.entry_id,
            "academy_id": current_academy_id(),
            "occurrence_id": entry.occurrence_id,
            "student_id": entry.student_id,
            "source": entry.source,
            "origin_request_id": entry.origin_request_id,
            "created_at": entry.created_at,
        }

    async def add(self, entry: OccurrenceRosterEntry) -> None:
        await self._insert_one(self._to_doc(entry))

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]:
        cursor = self._find_many({"occurrence_id": occurrence_id}, sort=[("created_at", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def exists(self, occurrence_id: str, student_id: str) -> bool:
        doc = await self._find_one({"occurrence_id": occurrence_id, "student_id": student_id})
        return doc is not None
