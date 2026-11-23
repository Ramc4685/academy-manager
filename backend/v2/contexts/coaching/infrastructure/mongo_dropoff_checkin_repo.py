"""Mongo DropoffCheckinRepository (``dropoff_checkins``, migration 0246).

One row per (academy, occurrence, student), held by a unique index, so a
repeat tap or two racing reports store one row. Status moves forward only:
every transition is a conditional ``find_one_and_update`` on the expected
status, so concurrent confirms cannot step on each other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.coaching.domain.dropoff import DropoffCheckin
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.time.mongo import ensure_utc

_KEY_FIELDS = ("academy_id", "occurrence_id", "student_id")


def _opt_utc(value: object) -> datetime | None:
    return ensure_utc(cast(datetime, value)) if value else None


class MongoDropoffCheckinRepository(TenantScopedRepository):
    collection_name = "dropoff_checkins"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> DropoffCheckin:
        return DropoffCheckin(
            checkin_id=str(doc["checkin_id"]),
            academy_id=str(doc["academy_id"]),
            occurrence_id=str(doc["occurrence_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            reported_by=str(doc["reported_by"]),
            reported_at=ensure_utc(cast(datetime, doc["reported_at"])),
            status=doc.get("status") or "reported",
            confirm_mutation_id=doc.get("confirm_mutation_id"),
            confirmed_by=doc.get("confirmed_by"),
            confirmed_at=_opt_utc(doc.get("confirmed_at")),
            attendance_id=doc.get("attendance_id"),
            reconciled_with_existing_mark=bool(doc.get("reconciled_with_existing_mark", False)),
        )

    @staticmethod
    def _key(occurrence_id: str, student_id: str) -> dict[str, str]:
        return {"occurrence_id": occurrence_id, "student_id": student_id}

    async def report(self, checkin: DropoffCheckin) -> DropoffCheckin:
        on_insert = {
            k: v for k, v in checkin.model_dump(mode="python").items() if k not in _KEY_FIELDS
        }
        try:
            await self._update_one(
                self._key(checkin.occurrence_id, checkin.student_id),
                {"$setOnInsert": on_insert},
                upsert=True,
            )
        except DuplicateKeyError:
            pass  # a concurrent report inserted the row first; read it back
        stored = await self.get(checkin.occurrence_id, checkin.student_id)
        if stored is None:  # pragma: no cover - the upsert above just wrote it
            raise RuntimeError("drop-off check-in upsert did not persist a row")
        return stored

    async def get(self, occurrence_id: str, student_id: str) -> DropoffCheckin | None:
        doc = await self._find_one(self._key(occurrence_id, student_id))
        return self._to_domain(doc) if doc else None

    async def begin_confirm(
        self, occurrence_id: str, student_id: str, *, confirm_mutation_id: str, staff_id: str
    ) -> DropoffCheckin | None:
        doc = await self._find_one_and_update(
            {**self._key(occurrence_id, student_id), "status": "reported"},
            {
                "$set": {
                    "status": "confirming",
                    "confirm_mutation_id": confirm_mutation_id,
                    "confirmed_by": staff_id,
                }
            },
        )
        if doc is not None:
            return self._to_domain(doc)
        return await self.get(occurrence_id, student_id)

    async def finish_confirm(
        self,
        occurrence_id: str,
        student_id: str,
        *,
        attendance_id: str,
        reconciled: bool,
        confirmed_at: datetime,
    ) -> DropoffCheckin | None:
        doc = await self._find_one_and_update(
            {**self._key(occurrence_id, student_id), "status": "confirming"},
            {
                "$set": {
                    "status": "confirmed",
                    "attendance_id": attendance_id,
                    "reconciled_with_existing_mark": reconciled,
                    "confirmed_at": confirmed_at,
                }
            },
        )
        if doc is not None:
            return self._to_domain(doc)
        return await self.get(occurrence_id, student_id)

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[DropoffCheckin]:
        if not occurrence_ids:
            return []
        cursor = self._find_many(
            {"occurrence_id": {"$in": occurrence_ids}}, sort=[("reported_at", 1)]
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_student(
        self, student_id: str, occurrence_ids: list[str]
    ) -> list[DropoffCheckin]:
        if not occurrence_ids:
            return []
        cursor = self._find_many(
            {"student_id": student_id, "occurrence_id": {"$in": occurrence_ids}}
        )
        return [self._to_domain(doc) async for doc in cursor]
