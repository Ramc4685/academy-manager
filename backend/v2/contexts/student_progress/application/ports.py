"""Student progress application ports (protocols)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from backend.v2.contexts.student_progress.domain.milestones import (
    ProgressSettings,
    StudentMilestone,
)
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
    async def complete(self, progress_id: str, completed_at: datetime) -> None: ...
    async def withdraw(self, progress_id: str, ended_at: datetime) -> None: ...
    async def list_active_for_level(self, level_id: str) -> list[StudentLevelProgress]: ...
    async def list_for_student(self, student_id: str) -> list[StudentLevelProgress]: ...
    async def list_active_for_students(
        self, student_ids: list[str], program_id: str
    ) -> list[StudentLevelProgress]: ...


class StudentSkillProgressRepository(Protocol):
    async def save(self, skill_progress: StudentSkillProgress) -> None: ...
    async def upsert(self, skill_progress: StudentSkillProgress) -> StudentSkillProgress: ...
    async def insert_if_missing(self, skill_progress: StudentSkillProgress) -> bool: ...
    async def increment_tries(self, student_id: str, skill_id: str, delta: int) -> int | None: ...
    async def add_try_once(self, student_id: str, skill_id: str, contribution_id: str) -> int:
        """Count ``contribution_id`` as one try at most once; its 1-based ordinal."""
        ...

    async def set_status_unless_passed(
        self,
        student_id: str,
        skill_id: str,
        status: str,
        *,
        at: datetime,
        by: str,
        introduced_at: datetime | None = None,
    ) -> bool: ...
    async def get(self, student_id: str, skill_id: str) -> StudentSkillProgress | None: ...
    async def set_coach_note(
        self, student_id: str, skill_id: str, *, passed_at: datetime, note: str | None
    ) -> bool: ...
    async def list_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]: ...
    async def list_for_student_program(
        self, student_id: str, program_id: str
    ) -> list[StudentSkillProgress]: ...
    async def list_passed_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]: ...
    async def list_passed_for_student(self, student_id: str) -> list[StudentSkillProgress]: ...
    async def list_recent_for_student(
        self, student_id: str, limit: int = 10
    ) -> list[StudentSkillProgress]: ...
    async def list_in_progress_for_student(self, student_id: str) -> list[StudentSkillProgress]: ...
    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]: ...
    async def count_updates_by_coach(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[dict[str, object]]: ...


class TestAttemptRepository(Protocol):
    async def save(self, attempt: TestAttempt) -> None: ...
    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[TestAttempt]: ...
    async def count_for_student_skill(self, student_id: str, skill_id: str) -> int: ...
    async def list_for_student_skills(
        self, student_id: str, skill_ids: list[str]
    ) -> list[TestAttempt]: ...
    async def get_by_observation(self, observation_key: str) -> TestAttempt | None: ...
    async def insert_observation(self, attempt: TestAttempt) -> bool:
        """Insert-only on ``observation_key``; False when it is already stored."""
        ...

    async def mark_effects_done(self, attempt_id: str, *, at: datetime) -> None: ...
    async def list_by_observations(self, observation_keys: list[str]) -> list[TestAttempt]: ...


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
    """Reads skip revoked certificates unless ``include_revoked`` (admin only)."""

    async def save(self, cert: SkillCertificate) -> None: ...
    async def list_for_student(
        self, student_id: str, *, include_revoked: bool = False
    ) -> list[SkillCertificate]: ...
    async def list_for_students(self, student_ids: list[str]) -> list[SkillCertificate]: ...
    async def revoke(
        self, student_id: str, cert_id: str, *, at: datetime, by: str, reason: str
    ) -> bool:
        """Issued -> revoked, dropping the share link. False when nothing was issued."""
        ...

    async def get_issued_by_share_token(self, token: str) -> SkillCertificate | None:
        """The issued certificate carrying this share link in the current academy."""
        ...

    async def set_share_token(self, student_id: str, cert_id: str, token: str) -> bool:
        """Mint the link on an issued certificate that has none. False otherwise."""
        ...

    async def clear_share_token(self, student_id: str, cert_id: str) -> bool:
        """Drop the link. False when there was none."""
        ...


class CertificateAuditLog(Protocol):
    async def record_revoked(self, cert: SkillCertificate) -> bool:
        """Write the one ``certificate.revoked`` row for this certificate.

        Idempotent: True only when this call wrote it, so a retry after a
        failed write can tell it still owes the audit row.
        """
        ...


class ProgressAuditLog(Protocol):
    async def record(
        self,
        *,
        audit_id: str,
        action: str,
        actor_id: str,
        entity_type: str,
        entity_id: str,
        before: dict[str, object],
        after: dict[str, object],
        at: datetime,
    ) -> bool:
        """Write one audit row keyed by ``audit_id`` (a retry never doubles it)."""
        ...


class ProgressSettingsStore(Protocol):
    async def get(self) -> ProgressSettings: ...

    async def set(self, settings: ProgressSettings) -> None:
        """Targeted write of the progress settings block only."""
        ...


class MilestoneRepository(Protocol):
    async def record(self, milestone: StudentMilestone) -> None:
        """Insert once per student and key; a repeat is a no-op."""
        ...

    async def list_for_student(self, student_id: str) -> list[StudentMilestone]: ...

    async def delete(self, student_id: str, milestone_key: str) -> None:
        """Drop a record the student no longer holds (an undone pass or a revoke)."""
        ...


class PlacementAuditLog(Protocol):
    async def record_placed(
        self,
        *,
        student_id: str,
        program_id: str,
        level_id: str,
        progress_id: str,
        placed_by: str,
        reason: str,
        credited_skill_ids: list[str],
    ) -> bool:
        """Write the one ``student.pathway_placed`` row for this placement.

        Idempotent (deterministic id): True only when this call wrote it.
        """
        ...


class CertificateNumbers(Protocol):
    """Mints the next human-facing certificate number for the current academy."""

    async def next_number(self) -> str: ...


class SkillLookup(Protocol):
    """Cross-context port: reads skill/level metadata from curriculum context."""

    async def get_skill(self, skill_id: str) -> object | None: ...
    async def get_level(self, level_id: str) -> object | None: ...
    async def list_skills_for_level(self, level_id: str) -> list[object]: ...
    async def list_skills_for_program(self, program_id: str) -> list[object]: ...
    async def get_next_level(self, program_id: str, current_sequence: int) -> object | None: ...
    async def list_levels_for_program(self, program_id: str) -> list[object]: ...


class CriterionLookup(Protocol):
    """Cross-context port: a skill's observable criteria, from the curriculum context."""

    async def list_for_skill(self, skill_id: str) -> Sequence[object]: ...


class EnrollmentStatusLookup(Protocol):
    """Cross-context port: does the student still attend (issue #673)?

    "Live" means an enrollment in ``active`` or ``paused`` status — the same
    predicate the coach passport uses (issue #651). Cancelled and withdrawn
    students are not live: they must not be recommended, approved, or
    certified, and their pending recommendations are expired.
    """

    async def has_active_or_paused_enrollment(self, student_id: str) -> bool: ...
    async def student_exists(self, student_id: str) -> bool:
        """The student is on this academy's books (tenant-scoped)."""
        ...

    async def students_with_active_or_paused_enrollment(self, student_ids: list[str]) -> set[str]:
        """Batch form for the queue: the subset of ``student_ids`` that is live."""
        ...
