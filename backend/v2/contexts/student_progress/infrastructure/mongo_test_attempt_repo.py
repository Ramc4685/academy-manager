"""Mongo TestAttemptRepository."""

from __future__ import annotations

from datetime import datetime

from pymongo.errors import DuplicateKeyError

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
            observed_at=doc.get("observed_at"),
            signed_off_by=str(doc["signed_off_by"]) if doc.get("signed_off_by") else None,
            observation_key=doc.get("observation_key"),
            effects_done_at=doc.get("effects_done_at"),
        )

    @staticmethod
    def _body(attempt: TestAttempt) -> dict[str, object]:
        body: dict[str, object] = {
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
            "observed_at": attempt.observed_at,
            "signed_off_by": attempt.signed_off_by,
        }
        if attempt.observation_key:
            # Absent (not null) on formal tests: the unique index is partial.
            body["observation_key"] = attempt.observation_key
            body["effects_done_at"] = attempt.effects_done_at
        return body

    async def save(self, attempt: TestAttempt) -> None:
        await self._insert_one(self._body(attempt))

    async def insert_observation(self, attempt: TestAttempt) -> bool:
        try:
            await self._insert_one(self._body(attempt))
        except DuplicateKeyError:
            return False
        return True

    async def get_by_observation(self, observation_key: str) -> TestAttempt | None:
        doc = await self._find_one({"observation_key": observation_key})
        return self._to_domain(doc) if doc else None

    async def list_by_observations(self, observation_keys: list[str]) -> list[TestAttempt]:
        if not observation_keys:
            return []
        cursor = self._find_many({"observation_key": {"$in": observation_keys}})
        return [self._to_domain(d) async for d in cursor]

    async def mark_effects_done(self, attempt_id: str, *, at: datetime) -> None:
        await self._update_one(
            {"attempt_id": attempt_id, "effects_done_at": None}, {"$set": {"effects_done_at": at}}
        )

    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[TestAttempt]:
        cursor = self._find_many(
            {"student_id": student_id, "skill_id": skill_id},
            sort=[("tested_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def count_for_student_skill(self, student_id: str, skill_id: str) -> int:
        return await self._count({"student_id": student_id, "skill_id": skill_id})

    async def list_for_student_skills(
        self, student_id: str, skill_ids: list[str]
    ) -> list[TestAttempt]:
        """Every attempt for these skills in one query (the passport's N+1 fix)."""
        if not skill_ids:
            return []
        cursor = self._find_many(
            {"student_id": student_id, "skill_id": {"$in": list(skill_ids)}},
            sort=[("tested_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
