"""MongoDB implementation of CurriculumVideoRefRepository."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.curriculum.domain.models import CurriculumVideoRef
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoCurriculumVideoRefRepository(TenantScopedRepository):
    collection_name = "curriculum_video_refs"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> CurriculumVideoRef:
        return CurriculumVideoRef(
            ref_id=str(doc["ref_id"]),
            academy_id=str(doc["academy_id"]),
            program_id=str(doc["program_id"]),
            scope=doc["scope"],
            level_id=str(doc["level_id"]),
            skill_id=(str(doc["skill_id"]) if doc.get("skill_id") is not None else None),
            title=str(doc["title"]),
            url=str(doc["url"]),
            display_order=int(doc.get("display_order", 0)),
            content_hash=str(doc.get("content_hash", "")),
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],
            created_by=str(doc.get("created_by", "")),
        )

    @staticmethod
    def _to_doc(ref: CurriculumVideoRef) -> dict[str, Any]:
        # academy_id is injected by TenantScopedRepository on write.
        return {
            "ref_id": ref.ref_id,
            "program_id": ref.program_id,
            "scope": ref.scope,
            "level_id": ref.level_id,
            "skill_id": ref.skill_id,
            "title": ref.title,
            "url": ref.url,
            "display_order": ref.display_order,
            "content_hash": ref.content_hash,
            "is_active": ref.is_active,
            "created_at": ref.created_at,
            "created_by": ref.created_by,
        }

    def _identity(
        self, *, scope: str, level_id: str, skill_id: str | None, url: str
    ) -> dict[str, Any]:
        return {"scope": scope, "level_id": level_id, "skill_id": skill_id, "url": url}

    async def get_by_identity(
        self, *, scope: str, level_id: str, skill_id: str | None, url: str
    ) -> CurriculumVideoRef | None:
        doc = await self._find_one(
            self._identity(scope=scope, level_id=level_id, skill_id=skill_id, url=url)
        )
        return self._to_domain(doc) if doc else None

    async def save(self, ref: CurriculumVideoRef) -> None:
        await self._insert_one(self._to_doc(ref))

    async def replace(self, ref: CurriculumVideoRef) -> None:
        await self._update_one(
            self._identity(
                scope=ref.scope, level_id=ref.level_id, skill_id=ref.skill_id, url=ref.url
            ),
            {"$set": self._to_doc(ref)},
        )

    async def list_for_level(self, level_id: str) -> list[CurriculumVideoRef]:
        cursor = self._find_many(
            {"scope": "LEVEL", "level_id": level_id}, sort=[("display_order", 1)]
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_skills(self, skill_ids: list[str]) -> list[CurriculumVideoRef]:
        if not skill_ids:
            return []
        cursor = self._find_many(
            {"scope": "SKILL", "skill_id": {"$in": skill_ids}}, sort=[("display_order", 1)]
        )
        return [self._to_domain(doc) async for doc in cursor]
