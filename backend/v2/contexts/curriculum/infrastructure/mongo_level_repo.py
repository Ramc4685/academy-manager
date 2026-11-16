"""MongoDB implementation of LevelRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.curriculum.domain.models import Level
from backend.v2.shared.tenancy import TenantScopedRepository

#: Lifts every row clear of 1..n during a reorder's first pass.
RESEQUENCE_OFFSET = 10_000


class MongoLevelRepository(TenantScopedRepository):
    collection_name = "skill_levels"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Level:
        return Level(
            level_id=str(doc["level_id"]),
            program_id=str(doc["program_id"]),
            academy_id=str(doc["academy_id"]),
            sequence=int(doc["sequence"]),
            name=str(doc["name"]),
            description=str(doc.get("description", "")),
            completion_rule=doc.get("completion_rule", "ALL_REQUIRED_SKILLS"),
            points_threshold=doc.get("points_threshold"),
            requires_coach_recommendation=bool(doc.get("requires_coach_recommendation", True)),
            requires_admin_approval=bool(doc.get("requires_admin_approval", False)),
            color=doc.get("color") or None,
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            created_by=str(doc.get("created_by", "")),
        )

    async def save(self, level: Level) -> None:
        await self._insert_one(
            {
                "level_id": level.level_id,
                "program_id": level.program_id,
                "sequence": level.sequence,
                "name": level.name,
                "description": level.description,
                "completion_rule": level.completion_rule,
                "points_threshold": level.points_threshold,
                "requires_coach_recommendation": level.requires_coach_recommendation,
                "requires_admin_approval": level.requires_admin_approval,
                "color": level.color,
                "is_active": level.is_active,
                "created_at": level.created_at,
                "updated_at": level.updated_at,
                "created_by": level.created_by,
            }
        )

    async def update(self, level: Level) -> None:
        await self._update_one(
            {"level_id": level.level_id},
            {
                "$set": {
                    "name": level.name,
                    "description": level.description,
                    "completion_rule": level.completion_rule,
                    "requires_coach_recommendation": level.requires_coach_recommendation,
                    "requires_admin_approval": level.requires_admin_approval,
                    "color": level.color,
                    "is_active": level.is_active,
                    "updated_at": level.updated_at,
                }
            },
        )

    async def get(self, level_id: str) -> Level | None:
        doc = await self._find_one({"level_id": level_id})
        return self._to_domain(doc) if doc else None

    async def list_for_program(self, program_id: str) -> list[Level]:
        cursor = self._find_many(
            {"program_id": program_id, "is_active": True},
            sort=[("sequence", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_all_for_program(self, program_id: str) -> list[Level]:
        """Active and retired levels, in sequence order (reorder needs both)."""
        cursor = self._find_many({"program_id": program_id}, sort=[("sequence", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def resequence(self, ordered_ids: list[str]) -> None:
        """Number ``ordered_ids`` 1..n in two passes, so the unique sequence
        index never sees two rows on one number mid-way.

        shortcut: not atomic; a crash between passes leaves sequences above
        RESEQUENCE_OFFSET (still ordered) until the next reorder.
        """
        now = datetime.now(UTC)
        for i, item_id in enumerate(ordered_ids, start=1):
            await self._update_one(
                {"level_id": item_id}, {"$set": {"sequence": RESEQUENCE_OFFSET + i}}
            )
        for i, item_id in enumerate(ordered_ids, start=1):
            await self._update_one(
                {"level_id": item_id}, {"$set": {"sequence": i, "updated_at": now}}
            )
