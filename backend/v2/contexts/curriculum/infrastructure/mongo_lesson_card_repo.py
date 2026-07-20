"""MongoDB implementation of LessonCardRepository."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.curriculum.domain.models import LessonCard, LessonResourceLink
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoLessonCardRepository(TenantScopedRepository):
    collection_name = "lesson_cards"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> LessonCard:
        return LessonCard(
            card_id=str(doc["card_id"]),
            academy_id=str(doc["academy_id"]),
            program_id=str(doc["program_id"]),
            level_id=str(doc["level_id"]),
            skill_ids=[str(s) for s in doc.get("skill_ids", [])],
            slug=str(doc["slug"]),
            lesson_number=int(doc["lesson_number"]),
            title=str(doc["title"]),
            goal_summary=str(doc.get("goal_summary", "")),
            teaching_points=[str(t) for t in doc.get("teaching_points", [])],
            equipment=[str(e) for e in doc.get("equipment", [])],
            activity_summary=str(doc.get("activity_summary", "")),
            safety_notes=[str(s) for s in doc.get("safety_notes", [])],
            source=doc.get("source", "BWF_SHUTTLE_TIME"),
            module_name=str(doc.get("module_name", "")),
            lesson_range=str(doc.get("lesson_range", "")),
            page_hint=doc.get("page_hint"),
            resource_links=[
                LessonResourceLink(
                    kind=link["kind"],
                    title=str(link["title"]),
                    url=link.get("url"),
                )
                for link in doc.get("resource_links", [])
            ],
            content_hash=str(doc.get("content_hash", "")),
            display_order=int(doc.get("display_order", 0)),
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            created_by=str(doc.get("created_by", "")),
        )

    @staticmethod
    def _to_doc(card: LessonCard) -> dict[str, Any]:
        # academy_id is injected by TenantScopedRepository on write.
        return {
            "card_id": card.card_id,
            "program_id": card.program_id,
            "level_id": card.level_id,
            "skill_ids": list(card.skill_ids),
            "slug": card.slug,
            "lesson_number": card.lesson_number,
            "title": card.title,
            "goal_summary": card.goal_summary,
            "teaching_points": list(card.teaching_points),
            "equipment": list(card.equipment),
            "activity_summary": card.activity_summary,
            "safety_notes": list(card.safety_notes),
            "source": card.source,
            "module_name": card.module_name,
            "lesson_range": card.lesson_range,
            "page_hint": card.page_hint,
            "resource_links": [
                {"kind": link.kind, "title": link.title, "url": link.url}
                for link in card.resource_links
            ],
            "content_hash": card.content_hash,
            "display_order": card.display_order,
            "is_active": card.is_active,
            "created_at": card.created_at,
            "updated_at": card.updated_at,
            "created_by": card.created_by,
        }

    async def get_by_slug(self, program_id: str, slug: str) -> LessonCard | None:
        doc = await self._find_one({"program_id": program_id, "slug": slug})
        return self._to_domain(doc) if doc else None

    async def save(self, card: LessonCard) -> None:
        await self._insert_one(self._to_doc(card))

    async def replace(self, card: LessonCard) -> None:
        await self._update_one(
            {"program_id": card.program_id, "slug": card.slug},
            {"$set": self._to_doc(card)},
        )

    async def list_for_program(self, program_id: str) -> list[LessonCard]:
        cursor = self._find_many({"program_id": program_id}, sort=[("display_order", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_skill(self, skill_id: str) -> list[LessonCard]:
        cursor = self._find_many({"skill_ids": skill_id}, sort=[("display_order", 1)])
        return [self._to_domain(doc) async for doc in cursor]
