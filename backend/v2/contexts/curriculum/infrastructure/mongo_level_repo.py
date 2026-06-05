"""MongoDB implementation of LevelRepository."""

from __future__ import annotations

from backend.v2.contexts.curriculum.domain.models import Level
from backend.v2.shared.tenancy import TenantScopedRepository


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
            completion_rule=doc.get("completion_rule", "ALL_REQUIRED_SKILLS"),  # type: ignore[arg-type]
            points_threshold=doc.get("points_threshold"),  # type: ignore[arg-type]
            requires_coach_recommendation=bool(doc.get("requires_coach_recommendation", True)),
            requires_admin_approval=bool(doc.get("requires_admin_approval", False)),
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
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
