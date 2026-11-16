"""Mongo StudentSkillProgressRepository."""

from __future__ import annotations

from datetime import datetime

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.student_progress.domain.models import StudentSkillProgress
from backend.v2.shared.tenancy import TenantScopedRepository

_IN_PROGRESS_STATUSES = ["INTRODUCED", "LEARNING", "PRACTICING", "TEST_READY", "NEEDS_REVIEW"]
_RECORDED_OUTCOME_STATUSES = [
    "INTRODUCED",
    "LEARNING",
    "PRACTICING",
    "TEST_READY",
    "PASSED",
    "NEEDS_REVIEW",
]


class MongoStudentSkillProgressRepository(TenantScopedRepository):
    collection_name = "student_skill_progress"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> StudentSkillProgress:
        return StudentSkillProgress(
            skill_progress_id=str(doc["skill_progress_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            skill_id=str(doc["skill_id"]),
            level_id=str(doc["level_id"]),
            program_id=str(doc["program_id"]),
            status=doc["status"],
            introduced_at=doc.get("introduced_at"),
            last_updated_at=doc["last_updated_at"],
            last_updated_by=str(doc["last_updated_by"]),
            coach_note=doc.get("coach_note") or None,
            tries=doc.get("tries") or 0,
            silent=bool(doc.get("silent", False)),
        )

    @staticmethod
    def _fields(skill_progress: StudentSkillProgress) -> dict[str, object]:
        # ``tries`` is deliberately absent: only ``increment_tries`` writes it.
        return {
            "skill_progress_id": skill_progress.skill_progress_id,
            "student_id": skill_progress.student_id,
            "skill_id": skill_progress.skill_id,
            "level_id": skill_progress.level_id,
            "program_id": skill_progress.program_id,
            "status": skill_progress.status,
            "introduced_at": skill_progress.introduced_at,
            "last_updated_at": skill_progress.last_updated_at,
            "last_updated_by": skill_progress.last_updated_by,
            "coach_note": skill_progress.coach_note,
            "silent": skill_progress.silent,
        }

    async def save(self, skill_progress: StudentSkillProgress) -> None:
        await self._insert_one(self._fields(skill_progress))

    async def upsert(self, skill_progress: StudentSkillProgress) -> StudentSkillProgress:
        await self._update_one(
            {"student_id": skill_progress.student_id, "skill_id": skill_progress.skill_id},
            {"$set": self._fields(skill_progress)},
            upsert=True,
        )
        saved = await self.get(skill_progress.student_id, skill_progress.skill_id)
        if saved is None:  # pragma: no cover - impossible unless Mongo write failed silently
            raise RuntimeError("skill progress upsert did not persist a row")
        return saved

    async def insert_if_missing(self, skill_progress: StudentSkillProgress) -> bool:
        """Create the row only when the student has none for this skill.

        Placement and level-up seed with this, so a skill the student already
        earned is never reset (the November wipe). Returns whether it inserted.
        """
        try:
            result = await self._update_one(
                {"student_id": skill_progress.student_id, "skill_id": skill_progress.skill_id},
                {"$setOnInsert": {**self._fields(skill_progress), "tries": 0}},
                upsert=True,
            )
        except DuplicateKeyError:  # a concurrent seed won the unique index
            return False
        return result.upserted_id is not None

    async def increment_tries(self, student_id: str, skill_id: str, delta: int) -> int | None:
        """Atomically add ``delta`` to ``tries`` (never below zero); the new count.

        ``None`` when there is no row, or a decrement found it already at zero.
        """
        filter_: dict[str, object] = {"student_id": student_id, "skill_id": skill_id}
        if delta < 0:
            filter_["tries"] = {"$gte": -delta}
        doc = await self._find_one_and_update(filter_, {"$inc": {"tries": delta}})
        return int(doc.get("tries") or 0) if doc else None

    async def set_status_unless_passed(
        self, student_id: str, skill_id: str, status: str, *, at: datetime, by: str
    ) -> bool:
        """Write a non-pass status, but never over a PASSED row: a stale try
        that read before a concurrent pass must not take the pass away."""
        result = await self._update_one(
            {"student_id": student_id, "skill_id": skill_id, "status": {"$ne": "PASSED"}},
            {"$set": {"status": status, "last_updated_at": at, "last_updated_by": by}},
        )
        return bool(result.matched_count == 1)

    async def set_coach_note(
        self, student_id: str, skill_id: str, *, passed_at: datetime, note: str | None
    ) -> bool:
        """Note-only write, and only on the same pass: an undo or re-tap in between wins."""
        result = await self._update_one(
            {
                "student_id": student_id,
                "skill_id": skill_id,
                "status": "PASSED",
                "last_updated_at": passed_at,
            },
            {"$set": {"coach_note": note}},
        )
        return bool(result.matched_count == 1)

    async def get(self, student_id: str, skill_id: str) -> StudentSkillProgress | None:
        doc = await self._find_one({"student_id": student_id, "skill_id": skill_id})
        return self._to_domain(doc) if doc else None

    async def list_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id, "level_id": level_id},
            sort=[("skill_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_passed_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id, "level_id": level_id, "status": "PASSED"},
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_passed_between(
        self, start: datetime, end: datetime
    ) -> list[StudentSkillProgress]:
        """Skills that reached PASSED in ``[start, end)`` -- the evening win email."""
        cursor = self._find_many(
            {
                "status": "PASSED",
                "last_updated_at": {"$gte": start, "$lt": end},
                "silent": {"$ne": True},
            },
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_recent_for_student(
        self, student_id: str, limit: int = 10
    ) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("last_updated_at", -1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_in_progress_for_student(self, student_id: str) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id, "status": {"$in": _IN_PROGRESS_STATUSES}},
            sort=[("last_updated_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]:
        if not student_ids:
            return []
        cursor = self._find_many(
            {"student_id": {"$in": list(student_ids)}, "level_id": level_id},
            sort=[("student_id", 1), ("skill_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def passed_stats_for_students(
        self, student_ids: list[str], program_id: str, *, since: datetime
    ) -> list[dict[str, object]]:
        """Per student: when the last skill was PASSED, and how many since ``since``."""
        if not student_ids:
            return []
        pipeline = [
            {
                "$match": self._scoped(
                    {
                        "student_id": {"$in": list(student_ids)},
                        "program_id": program_id,
                        "status": "PASSED",
                    }
                )
            },
            {
                "$group": {
                    "_id": "$student_id",
                    "last_passed_at": {"$max": "$last_updated_at"},
                    "passed_since": {
                        "$sum": {"$cond": [{"$gte": ["$last_updated_at", since]}, 1, 0]}
                    },
                }
            },
        ]
        return [
            {
                "student_id": str(doc["_id"]),
                "last_passed_at": doc["last_passed_at"],
                "passed_since": int(doc["passed_since"]),
            }
            async for doc in self.collection.aggregate(pipeline)
        ]

    async def count_updates_by_coach(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[dict[str, object]]:
        pipeline = [
            {
                "$match": self._scoped(
                    {
                        "last_updated_at": {"$gte": start_at, "$lte": end_at},
                        "last_updated_by": {"$nin": [None, ""]},
                        "status": {"$in": _RECORDED_OUTCOME_STATUSES},
                    }
                )
            },
            {"$group": {"_id": "$last_updated_by", "outcomes_recorded": {"$sum": 1}}},
            {"$sort": {"outcomes_recorded": -1, "_id": 1}},
        ]
        cursor = self.collection.aggregate(pipeline)
        return [
            {
                "coach_id": str(doc["_id"]),
                "outcomes_recorded": int(doc.get("outcomes_recorded", 0)),
            }
            async for doc in cursor
        ]
