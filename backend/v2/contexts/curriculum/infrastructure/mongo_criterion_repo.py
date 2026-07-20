"""MongoDB implementation of CriterionRepository."""

from __future__ import annotations

from backend.v2.contexts.curriculum.domain.models import SkillCriterion
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoCriterionRepository(TenantScopedRepository):
    collection_name = "skill_criteria"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> SkillCriterion:
        return SkillCriterion(
            criterion_id=str(doc["criterion_id"]),
            skill_id=str(doc["skill_id"]),
            level_id=str(doc["level_id"]),
            program_id=str(doc["program_id"]),
            academy_id=str(doc["academy_id"]),
            description=str(doc["description"]),
            display_order=int(doc.get("display_order", 0)),
            created_at=doc["created_at"],
            created_by=str(doc.get("created_by", "")),
        )

    async def save(self, criterion: SkillCriterion) -> None:
        await self._insert_one(
            {
                "criterion_id": criterion.criterion_id,
                "skill_id": criterion.skill_id,
                "level_id": criterion.level_id,
                "program_id": criterion.program_id,
                "description": criterion.description,
                "display_order": criterion.display_order,
                "created_at": criterion.created_at,
                "created_by": criterion.created_by,
            }
        )

    async def list_for_skill(self, skill_id: str) -> list[SkillCriterion]:
        cursor = self._find_many(
            {"skill_id": skill_id},
            sort=[("display_order", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
