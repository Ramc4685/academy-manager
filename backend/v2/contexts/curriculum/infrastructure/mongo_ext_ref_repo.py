"""MongoDB implementation of ExternalRefRepository."""

from __future__ import annotations

from backend.v2.contexts.curriculum.domain.models import ExternalLessonReference
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoExternalRefRepository(TenantScopedRepository):
    collection_name = "external_lesson_refs"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> ExternalLessonReference:
        return ExternalLessonReference(
            ref_id=str(doc["ref_id"]),
            skill_id=str(doc["skill_id"]),
            academy_id=str(doc["academy_id"]),
            source=doc["source"],
            source_title=str(doc["source_title"]),
            module_name=str(doc["module_name"]),
            lesson_range=str(doc["lesson_range"]),
            reference_title=str(doc["reference_title"]),
            page_hint=doc.get("page_hint"),
            internal_note=str(doc.get("internal_note", "")),
            created_at=doc["created_at"],
            created_by=str(doc.get("created_by", "")),
        )

    async def save(self, ref: ExternalLessonReference) -> None:
        await self._insert_one(
            {
                "ref_id": ref.ref_id,
                "skill_id": ref.skill_id,
                "source": ref.source,
                "source_title": ref.source_title,
                "module_name": ref.module_name,
                "lesson_range": ref.lesson_range,
                "reference_title": ref.reference_title,
                "page_hint": ref.page_hint,
                "internal_note": ref.internal_note,
                "created_at": ref.created_at,
                "created_by": ref.created_by,
            }
        )

    async def list_for_skill(self, skill_id: str) -> list[ExternalLessonReference]:
        cursor = self._find_many({"skill_id": skill_id})
        return [self._to_domain(doc) async for doc in cursor]
