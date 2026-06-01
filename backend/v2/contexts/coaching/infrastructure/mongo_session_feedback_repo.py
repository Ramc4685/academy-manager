"""Mongo repository for coach-authored session feedback."""

from __future__ import annotations

from backend.v2.contexts.coaching.domain.models import SessionFeedback
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSessionFeedbackRepository(TenantScopedRepository):
    collection_name = "session_feedback"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> SessionFeedback:
        return SessionFeedback(
            feedback_id=str(doc["feedback_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            occurrence_id=(
                str(doc["occurrence_id"]) if doc.get("occurrence_id") is not None else None
            ),
            coach_id=str(doc["coach_id"]),
            student_id=str(doc["student_id"]),
            body=str(doc.get("body") or ""),
            rating=doc.get("rating"),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
        )

    async def save(self, feedback: SessionFeedback) -> None:
        await self._insert_one(feedback.model_dump(mode="python"))

    async def list_for_session(self, session_id: str, *, limit: int = 100) -> list[SessionFeedback]:
        cursor = self._find_many(
            {"session_id": session_id},
            sort=[("created_at", -1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_student(self, student_id: str, *, limit: int = 100) -> list[SessionFeedback]:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("created_at", -1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]
