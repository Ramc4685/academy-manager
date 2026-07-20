"""Mongo repository for coach skill notes."""

from __future__ import annotations

from backend.v2.contexts.coaching.domain.models import CoachSkillNote
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSkillNoteRepository(TenantScopedRepository):
    collection_name = "coach_skill_notes"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> CoachSkillNote:
        return CoachSkillNote(
            note_id=str(doc["note_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            skill_id=str(doc["skill_id"]),
            coach_id=str(doc["coach_id"]),
            session_id=str(doc["session_id"]) if doc.get("session_id") is not None else None,
            body=str(doc.get("body") or ""),
            created_at=doc["created_at"],
        )

    async def save(self, note: CoachSkillNote) -> None:
        await self._insert_one(
            {
                "note_id": note.note_id,
                "student_id": note.student_id,
                "skill_id": note.skill_id,
                "coach_id": note.coach_id,
                "session_id": note.session_id,
                "body": note.body,
                "created_at": note.created_at,
            }
        )

    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[CoachSkillNote]:
        cursor = self._find_many(
            {"student_id": student_id, "skill_id": skill_id},
            sort=[("created_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_student(self, student_id: str) -> list[CoachSkillNote]:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("created_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
