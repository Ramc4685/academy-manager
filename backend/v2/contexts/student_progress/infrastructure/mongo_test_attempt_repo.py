"""Mongo TestAttemptRepository."""

from __future__ import annotations

from backend.v2.contexts.student_progress.domain.models import TestAttempt
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoTestAttemptRepository(TenantScopedRepository):
    collection_name = "test_attempts"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> TestAttempt:
        return TestAttempt(
            attempt_id=str(doc["attempt_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            skill_id=str(doc["skill_id"]),
            level_id=str(doc["level_id"]),
            program_id=str(doc["program_id"]),
            session_id=str(doc["session_id"]) if doc.get("session_id") else None,
            occurrence_id=str(doc["occurrence_id"]) if doc.get("occurrence_id") else None,
            coach_id=str(doc["coach_id"]),
            scoring_type=str(doc["scoring_type"]),
            attempts_count=int(doc["attempts_count"]),
            success_count=int(doc["success_count"]),
            score=float(doc["score"]),  # type: ignore[arg-type]
            passed=bool(doc["passed"]),
            coach_override=bool(doc.get("coach_override", False)),
            override_reason=str(doc["override_reason"]) if doc.get("override_reason") else None,
            notes=str(doc.get("notes", "")),
            tested_at=doc["tested_at"],
        )

    async def save(self, attempt: TestAttempt) -> None:
        await self._insert_one(
            {
                "attempt_id": attempt.attempt_id,
                "student_id": attempt.student_id,
                "skill_id": attempt.skill_id,
                "level_id": attempt.level_id,
                "program_id": attempt.program_id,
                "session_id": attempt.session_id,
                "occurrence_id": attempt.occurrence_id,
                "coach_id": attempt.coach_id,
                "scoring_type": attempt.scoring_type,
                "attempts_count": attempt.attempts_count,
                "success_count": attempt.success_count,
                "score": attempt.score,
                "passed": attempt.passed,
                "coach_override": attempt.coach_override,
                "override_reason": attempt.override_reason,
                "notes": attempt.notes,
                "tested_at": attempt.tested_at,
            }
        )

    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[TestAttempt]:
        cursor = self._find_many(
            {"student_id": student_id, "skill_id": skill_id},
            sort=[("tested_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def count_for_student_skill(self, student_id: str, skill_id: str) -> int:
        return await self._count({"student_id": student_id, "skill_id": skill_id})
