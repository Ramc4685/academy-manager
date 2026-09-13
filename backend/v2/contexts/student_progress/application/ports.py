"""Student progress application ports (protocols)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
    TestAttempt,
)


class StudentLevelProgressRepository(Protocol):
    async def save(self, progress: StudentLevelProgress) -> None: ...
    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None: ...
    async def get_by_id(self, progress_id: str) -> StudentLevelProgress | None: ...
    async def complete(self, progress_id: str, completed_at: object) -> None: ...
    async def list_for_student(self, student_id: str) -> list[StudentLevelProgress]: ...
    async def list_active_for_students(
        self, student_ids: list[str], program_id: str
    ) -> list[StudentLevelProgress]: ...


class StudentSkillProgressRepository(Protocol):
    async def save(self, skill_progress: StudentSkillProgress) -> None: ...
    async def upsert(self, skill_progress: StudentSkillProgress) -> StudentSkillProgress: ...
    async def get(self, student_id: str, skill_id: str) -> StudentSkillProgress | None: ...
    async def list_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]: ...
    async def list_passed_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]: ...
    async def list_recent_for_student(
        self, student_id: str, limit: int = 10
    ) -> list[StudentSkillProgress]: ...
    async def list_in_progress_for_student(self, student_id: str) -> list[StudentSkillProgress]: ...
    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]: ...
    async def count_updates_by_coach(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[object]: ...


class TestAttemptRepository(Protocol):
    async def save(self, attempt: TestAttempt) -> None: ...
    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[TestAttempt]: ...
    async def count_for_student_skill(self, student_id: str, skill_id: str) -> int: ...


class LevelUpRecommendationRepository(Protocol):
    async def save(self, rec: LevelUpRecommendation) -> None: ...
    async def claim(
        self,
        rec_id: str,
        claim_status: str,
        claimed_at: datetime,
        *,
        lease: timedelta,
    ) -> bool:
        """Reserve an undecided recommendation for one reviewer (issue #548).

        Compare-and-set into ``claim_status`` ("APPROVING" / "REJECTING"),
        stamping ``claimed_at``, when the stored status is either
        ``RECOMMENDED`` or an existing claim whose ``claimed_at`` is older
        than ``claimed_at - lease``. Returns whether the claim was taken.

        This is the point of no return for a review, and it exists because
        the approval's side effects (certificate, level advance, skill
        seeding) cannot be undone: without it, a reject that committed while
        an approval was mid-flight left the row REJECTED with a certificate
        already issued. The claim serialises the two, so the loser is refused
        before anything is written.

        The lease is what keeps a dead reviewer from parking the row
        forever — there is no recovery job. A reviewer that fails cleanly
        releases its own claim; only a process that dies mid-review leaves
        one to time out.
        """
        ...

    async def release(self, rec_id: str, *, claim_status: str) -> bool:
        """Hand a claim back unused: ``claim_status`` -> ``RECOMMENDED``.

        Called when a review fails after claiming but before recording a
        decision, so the admin can simply try again instead of waiting out
        the lease. Compare-and-set, so a claim already superseded (reclaimed
        after its lease expired, say) is left alone.
        """
        ...

    async def update_status(
        self,
        rec_id: str,
        status: str,
        reviewed_by: str | None,
        reviewed_at: datetime | None,
        rejection_reason: str | None,
        *,
        expected_status: str,
    ) -> bool:
        """Move a recommendation from ``expected_status`` to ``status``.

        Always a compare-and-set: the write applies only while the stored
        status still matches ``expected_status``. There is deliberately no
        unconditional variant — an unguarded status write is what let a
        replayed review be recorded twice. Returns whether the transition was
        applied, so callers can make the decision (and its side effects)
        land at most once.
        """
        ...

    async def get(self, rec_id: str) -> LevelUpRecommendation | None: ...
    async def get_active_for_student(
        self, student_id: str, program_id: str
    ) -> LevelUpRecommendation | None: ...
    async def list_active_for_students(
        self, student_ids: list[str], program_id: str
    ) -> list[LevelUpRecommendation]: ...
    async def list_pending(self) -> list[LevelUpRecommendation]: ...
    async def list_recommended_for_student(
        self, student_id: str
    ) -> list[LevelUpRecommendation]: ...


class CertificateRepository(Protocol):
    async def save(self, cert: SkillCertificate) -> None: ...
    async def list_for_student(self, student_id: str) -> list[SkillCertificate]: ...
    async def list_for_students(self, student_ids: list[str]) -> list[SkillCertificate]: ...


class SkillLookup(Protocol):
    """Cross-context port: reads skill/level metadata from curriculum context."""

    async def get_skill(self, skill_id: str) -> object | None: ...
    async def get_level(self, level_id: str) -> object | None: ...
    async def list_skills_for_level(self, level_id: str) -> list[object]: ...
    async def get_next_level(self, program_id: str, current_sequence: int) -> object | None: ...


class EnrollmentStatusLookup(Protocol):
    """Cross-context port: does the student still attend (issue #673)?

    "Live" means an enrollment in ``active`` or ``paused`` status — the same
    predicate the coach passport uses (issue #651). Cancelled and withdrawn
    students are not live: they must not be recommended, approved, or
    certified, and their pending recommendations are expired.
    """

    async def has_active_or_paused_enrollment(self, student_id: str) -> bool: ...
    async def students_with_active_or_paused_enrollment(self, student_ids: list[str]) -> set[str]:
        """Batch form for the queue: the subset of ``student_ids`` that is live."""
        ...
