"""MongoDB implementation of LevelDeletionStore.

Reads the other contexts' collections by field name only (no imports), always
through ``_scoped`` so every count and delete stays inside the current academy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.curriculum.domain.models import Level
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository

#: (collection, field holding a level_id, label in the "in use" report)
_LEVEL_REFERENCES: tuple[tuple[str, str, str], ...] = (
    ("student_level_progress", "level_id", "student_placements"),
    ("student_skill_progress", "level_id", "skill_progress_rows"),
    ("test_attempts", "level_id", "test_attempts"),
    ("skill_certificates", "level_id", "certificates"),
    ("lesson_cards", "level_id", "lesson_cards"),
    ("curriculum_video_refs", "level_id", "video_refs"),
)

#: (collection, field holding a skill_id, label)
_SKILL_REFERENCES: tuple[tuple[str, str, str], ...] = (
    ("student_skill_progress", "skill_id", "skill_progress_rows"),
    ("test_attempts", "skill_id", "test_attempts"),
    ("coach_skill_notes", "skill_id", "coach_skill_notes"),
    ("external_lesson_refs", "skill_id", "external_refs"),
)


class _AuditLogs(TenantScopedRepository):
    """Same ``audit_logs`` row shape as the other writers (``MongoPushTokenAudit``)."""

    collection_name = "audit_logs"

    async def insert(self, row: dict[str, Any]) -> None:
        await self._insert_one(row)


class MongoLevelDeletionStore(TenantScopedRepository):
    collection_name = "skill_levels"

    def __init__(self, db: Any) -> None:
        super().__init__(db)
        self._audit = _AuditLogs(db)

    async def _group_counts(self, collection: str, field: str, ids: list[str]) -> dict[str, int]:
        pipeline = [
            {"$match": self._scoped({field: {"$in": ids}})},
            {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
        ]
        return {row["_id"]: row["n"] async for row in self._db[collection].aggregate(pipeline)}

    async def usage_by_level(self, level_ids: list[str]) -> dict[str, dict[str, int]]:
        usage: dict[str, dict[str, int]] = {lid: {} for lid in level_ids}

        def add(level_id: str, label: str, n: int) -> None:
            # max, not sum: progress and attempts are checked by level and by skill.
            bucket = usage[level_id]
            bucket[label] = max(bucket.get(label, 0), n)

        for collection, field, label in _LEVEL_REFERENCES:
            for level_id, n in (await self._group_counts(collection, field, level_ids)).items():
                add(level_id, label, n)
        # Recommendations count once per row even when from and to are both this level.
        recs = self._db["level_up_recommendations"].find(
            self._scoped(
                {
                    "$or": [
                        {"from_level_id": {"$in": level_ids}},
                        {"to_level_id": {"$in": level_ids}},
                    ]
                }
            ),
            {"from_level_id": 1, "to_level_id": 1},
        )
        rec_counts: dict[str, int] = {}
        async for rec in recs:
            for lid in {rec.get("from_level_id"), rec.get("to_level_id")} & set(level_ids):
                rec_counts[lid] = rec_counts.get(lid, 0) + 1
        for lid, n in rec_counts.items():
            usage[lid]["level_up_recommendations"] = n

        skill_level: dict[str, str] = {
            str(doc["skill_id"]): str(doc["level_id"])
            async for doc in self._db["skills"].find(
                self._scoped({"level_id": {"$in": level_ids}}), {"skill_id": 1, "level_id": 1}
            )
        }
        if skill_level:
            for collection, field, label in _SKILL_REFERENCES:
                per_skill = await self._group_counts(collection, field, list(skill_level))
                per_level: dict[str, int] = {}
                for skill_id, n in per_skill.items():
                    per_level[skill_level[skill_id]] = per_level.get(skill_level[skill_id], 0) + n
                for level_id, n in per_level.items():
                    add(level_id, label, n)
        return usage

    async def delete_level(self, level_id: str) -> dict[str, int]:
        # Children first: a failure part way leaves the level visible to delete again.
        criteria = await self._db["skill_criteria"].delete_many(
            self._scoped({"level_id": level_id})
        )
        skills = await self._db["skills"].delete_many(self._scoped({"level_id": level_id}))
        levels = await self.collection.delete_many(self._scoped({"level_id": level_id}))
        return {
            "levels": levels.deleted_count,
            "skills": skills.deleted_count,
            "criteria": criteria.deleted_count,
        }

    async def record_deleted(self, *, level: Level, deleted: dict[str, int], actor_id: str) -> None:
        before: dict[str, Any] = {
            "program_id": level.program_id,
            "sequence": level.sequence,
            "name": level.name,
            **{f"{k}_deleted": v for k, v in deleted.items()},
        }
        await self._audit.insert(
            {
                "audit_id": new_ulid(),
                "actor_id": actor_id,
                "action": "curriculum.level_deleted",
                "entity_type": "skill_level",
                "entity_id": level.level_id,
                "reason": "admin deleted an unused level from the program editor",
                "changed_keys": [],
                "before": before,
                "after": None,
                "created_at": datetime.now(UTC),
            }
        )
