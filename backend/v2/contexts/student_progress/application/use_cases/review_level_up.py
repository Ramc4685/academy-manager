"""Use case: admin approves or rejects a level-up recommendation."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.errors import (
    RecommendationAlreadyReviewed,
    RecommendationNotFound,
)
from backend.v2.contexts.student_progress.domain.events import (
    CertificateIssued,
    CertificateIssuedPayload,
    StudentLeveledUp,
    StudentLeveledUpPayload,
)
from backend.v2.contexts.student_progress.domain.logic import generate_cert_number
from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id

PENDING_STATUS = "RECOMMENDED"


def _resolve_academy_id() -> str:
    return current_academy_id()


class ReviewLevelUpCommand(BaseModel):
    model_config = {"frozen": True}
    rec_id: str
    action: str  # "approve" or "reject"
    reviewed_by: str
    rejection_reason: str | None = None
    # Required for approve to build the certificate
    student_name: str = ""
    level_name: str = ""
    program_name: str = ""
    level_sequence: int = 1


class ReviewLevelUpResult(BaseModel):
    model_config = {"frozen": True}
    rec_id: str
    status: str
    cert_id: str | None


class ReviewLevelUpRecommendation:
    def __init__(
        self,
        *,
        recommendations: LevelUpRecommendationRepository,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        certificates: CertificateRepository,
        skill_lookup: SkillLookup,
        outbox: Outbox | None = None,
    ) -> None:
        self._recs = recommendations
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._certs = certificates
        self._skill_lookup = skill_lookup
        self._outbox = outbox

    async def execute(self, cmd: ReviewLevelUpCommand) -> ReviewLevelUpResult:
        rec = await self._recs.get(cmd.rec_id)
        if rec is None:
            raise RecommendationNotFound("recommendation not found", rec_id=cmd.rec_id)
        if rec.status != PENDING_STATUS:
            # Ordinary replay (a re-submitted form, a retried request): the
            # decision is already recorded, so refuse before touching anything.
            raise RecommendationAlreadyReviewed(
                "recommendation has already been reviewed",
                rec_id=cmd.rec_id,
                status=rec.status,
            )

        now = datetime.now(UTC)
        # (cert_id, cert_number, progress_id) once the approval has been applied.
        approval: tuple[str, str, str | None] | None = None
        decision = "APPROVED" if cmd.action == "approve" else "REJECTED"

        if cmd.action == "approve":
            # Approval side effects run *before* the status stamp and every one
            # of them is idempotent, so the status transition below is the
            # commit point. Two consequences, both deliberate:
            #   * a failure part-way through leaves the recommendation
            #     RECOMMENDED, so the admin can simply approve again — it never
            #     parks in APPROVED-with-no-certificate, which would also count
            #     as an active recommendation and block the student from ever
            #     being re-recommended;
            #   * the loser of a genuine double-click race re-applies the same
            #     writes (no duplicate certificate, no second active level row,
            #     no re-seeded skills) and is then refused by the CAS.
            approval = await self._apply_approval(rec, cmd, now)

        # Compare-and-set: only the caller that finds the recommendation still
        # pending records the decision.
        claimed = await self._recs.update_status(
            cmd.rec_id,
            decision,
            cmd.reviewed_by,
            now,
            cmd.rejection_reason if cmd.action != "approve" else None,
            expected_status=PENDING_STATUS,
        )
        if not claimed:
            # Report the authoritative post-CAS state, not the status read
            # before the race was lost.
            current = await self._recs.get(cmd.rec_id)
            raise RecommendationAlreadyReviewed(
                "recommendation has already been reviewed",
                rec_id=cmd.rec_id,
                status=current.status if current is not None else "UNKNOWN",
            )

        if approval is not None and self._outbox is not None:
            cert_id, cert_number, new_progress_id = approval
            academy_id = _resolve_academy_id()
            await self._outbox.append(
                StudentLeveledUp(
                    aggregate_id=rec.rec_id,
                    academy_id=academy_id,
                    payload=StudentLeveledUpPayload(
                        student_id=rec.student_id,
                        from_level_id=rec.from_level_id,
                        to_level_id=rec.to_level_id,
                        program_id=rec.program_id,
                        new_progress_id=new_progress_id or "",
                        cert_id=cert_id,
                    ),
                )
            )
            await self._outbox.append(
                CertificateIssued(
                    aggregate_id=cert_id,
                    academy_id=academy_id,
                    payload=CertificateIssuedPayload(
                        cert_id=cert_id,
                        cert_number=cert_number,
                        student_id=rec.student_id,
                        level_id=rec.from_level_id,
                        program_id=rec.program_id,
                        issued_by=cmd.reviewed_by,
                    ),
                )
            )

        return ReviewLevelUpResult(
            rec_id=cmd.rec_id,
            status=decision,
            cert_id=approval[0] if approval is not None else None,
        )

    async def _apply_approval(
        self,
        rec: LevelUpRecommendation,
        cmd: ReviewLevelUpCommand,
        now: datetime,
    ) -> tuple[str, str, str | None]:
        """Advance the student and issue the certificate, idempotently.

        Returns ``(cert_id, cert_number, progress_id)``.
        """
        active = await self._level_progress.get_active(rec.student_id, rec.program_id)
        advancing = rec.to_level_id != rec.from_level_id
        # A previous partial approval may already have moved the student on.
        already_advanced = advancing and active is not None and active.level_id == rec.to_level_id

        if active is not None and not already_advanced:
            await self._level_progress.complete(active.progress_id, now)

        # When the student is already on the target level, ``active`` *is* the
        # row a previous attempt created.
        progress_id = active.progress_id if active is not None else None
        if advancing:
            if not already_advanced:
                new_progress = StudentLevelProgress(
                    progress_id=str(new_ulid()),
                    academy_id=rec.academy_id,
                    student_id=rec.student_id,
                    program_id=rec.program_id,
                    level_id=rec.to_level_id,
                    status="active",
                    started_at=now,
                    completed_at=None,
                    created_at=now,
                )
                progress_id = new_progress.progress_id
                await self._level_progress.save(new_progress)

            # Seed NOT_STARTED skill records for the new level. Skills that
            # already have a row are left untouched: a retried approval must
            # never reset progress the student earned in the meantime.
            new_skills = await self._skill_lookup.list_skills_for_level(rec.to_level_id)
            for skill in new_skills:
                skill_id: str = skill.skill_id  # type: ignore[attr-defined]
                if await self._skill_progress.get(rec.student_id, skill_id) is not None:
                    continue
                sp = StudentSkillProgress(
                    skill_progress_id=str(new_ulid()),
                    academy_id=rec.academy_id,
                    student_id=rec.student_id,
                    skill_id=skill_id,
                    level_id=rec.to_level_id,
                    program_id=rec.program_id,
                    status="NOT_STARTED",
                    introduced_at=None,
                    last_updated_at=now,
                    last_updated_by=cmd.reviewed_by,
                )
                await self._skill_progress.upsert(sp)

        # One certificate per completed level: reuse the one a partial approval
        # already issued rather than minting a second.
        existing = await self._existing_certificate(rec)
        if existing is not None:
            return existing.cert_id, existing.cert_number, progress_id

        cert_id = str(new_ulid())
        timestamp_ms = int(now.timestamp() * 1000)
        cert_number = generate_cert_number(
            rec.academy_id, rec.student_id, cmd.level_sequence, timestamp_ms
        )
        await self._certs.save(
            SkillCertificate(
                cert_id=cert_id,
                academy_id=rec.academy_id,
                student_id=rec.student_id,
                program_id=rec.program_id,
                level_id=rec.from_level_id,
                cert_number=cert_number,
                student_name=cmd.student_name,
                level_name=cmd.level_name,
                program_name=cmd.program_name,
                completed_at=now,
                issued_by=cmd.reviewed_by,
                issued_at=now,
            )
        )
        return cert_id, cert_number, progress_id

    async def _existing_certificate(self, rec: LevelUpRecommendation) -> SkillCertificate | None:
        for cert in await self._certs.list_for_student(rec.student_id):
            if cert.program_id == rec.program_id and cert.level_id == rec.from_level_id:
                return cert
        return None
