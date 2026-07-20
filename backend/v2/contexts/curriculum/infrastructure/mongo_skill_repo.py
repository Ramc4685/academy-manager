"""MongoDB implementation of SkillRepository."""

from __future__ import annotations

from backend.v2.contexts.curriculum.domain.models import Skill
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSkillRepository(TenantScopedRepository):
    collection_name = "skills"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Skill:
        return Skill(
            skill_id=str(doc["skill_id"]),
            level_id=str(doc["level_id"]),
            program_id=str(doc["program_id"]),
            academy_id=str(doc["academy_id"]),
            sequence=int(doc["sequence"]),
            name=str(doc["name"]),
            description=str(doc.get("description", "")),
            is_required=bool(doc.get("is_required", True)),
            scoring_type=doc.get("scoring_type", "ATTEMPT_BASED"),
            pass_threshold_pct=float(doc.get("pass_threshold_pct", 70.0)),
            coach_override_allowed=bool(doc.get("coach_override_allowed", False)),
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            created_by=str(doc.get("created_by", "")),
        )

    async def save(self, skill: Skill) -> None:
        await self._insert_one(
            {
                "skill_id": skill.skill_id,
                "level_id": skill.level_id,
                "program_id": skill.program_id,
                "sequence": skill.sequence,
                "name": skill.name,
                "description": skill.description,
                "is_required": skill.is_required,
                "scoring_type": skill.scoring_type,
                "pass_threshold_pct": skill.pass_threshold_pct,
                "coach_override_allowed": skill.coach_override_allowed,
                "is_active": skill.is_active,
                "created_at": skill.created_at,
                "updated_at": skill.updated_at,
                "created_by": skill.created_by,
            }
        )

    async def update(self, skill: Skill) -> None:
        await self._update_one(
            {"skill_id": skill.skill_id},
            {
                "$set": {
                    "name": skill.name,
                    "description": skill.description,
                    "is_required": skill.is_required,
                    "scoring_type": skill.scoring_type,
                    "pass_threshold_pct": skill.pass_threshold_pct,
                    "coach_override_allowed": skill.coach_override_allowed,
                    "is_active": skill.is_active,
                    "updated_at": skill.updated_at,
                }
            },
        )

    async def get(self, skill_id: str) -> Skill | None:
        doc = await self._find_one({"skill_id": skill_id})
        return self._to_domain(doc) if doc else None

    async def list_for_level(self, level_id: str) -> list[Skill]:
        cursor = self._find_many(
            {"level_id": level_id, "is_active": True},
            sort=[("sequence", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_program(self, program_id: str) -> list[Skill]:
        cursor = self._find_many(
            {"program_id": program_id, "is_active": True},
            sort=[("sequence", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
