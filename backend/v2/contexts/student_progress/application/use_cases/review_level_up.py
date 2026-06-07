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
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


def _resolve_academy_id() -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return ""


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

        now = datetime.now(UTC)
        cert_id: str | None = None
        new_progress_id: str | None = None

        if cmd.action == "approve":
            # Complete current level progress
            active = await self._level_progress.get_active(rec.student_id, rec.program_id)
            if active:
                await self._level_progress.complete(active.progress_id, now)

            # Create new level progress for next level
            if rec.to_level_id != rec.from_level_id:
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
                new_progress_id = new_progress.progress_id
                await self._level_progress.save(new_progress)

                # Seed NOT_STARTED skill records for new level
                new_skills = await self._skill_lookup.list_skills_for_level(rec.to_level_id)
                for skill in new_skills:
                    sp = StudentSkillProgress(
                        skill_progress_id=str(new_ulid()),
                        academy_id=rec.academy_id,
                        student_id=rec.student_id,
                        skill_id=skill.skill_id,  # type: ignore[attr-defined]
                        level_id=rec.to_level_id,
                        program_id=rec.program_id,
                        status="NOT_STARTED",
                        introduced_at=None,
                        last_updated_at=now,
                        last_updated_by=cmd.reviewed_by,
                    )
                    await self._skill_progress.upsert(sp)

            # Issue certificate
            cert_id = str(new_ulid())
            timestamp_ms = int(now.timestamp() * 1000)
            cert_number = generate_cert_number(
                rec.academy_id, rec.student_id, cmd.level_sequence, timestamp_ms
            )
            cert = SkillCertificate(
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
            await self._certs.save(cert)

            await self._recs.update_status(cmd.rec_id, "APPROVED", cmd.reviewed_by, now, None)

            if self._outbox is not None:
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
                            new_progress_id=new_progress_id
                            or (active.progress_id if active is not None else ""),
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

        else:  # reject
            await self._recs.update_status(
                cmd.rec_id, "REJECTED", cmd.reviewed_by, now, cmd.rejection_reason
            )

        return ReviewLevelUpResult(
            rec_id=cmd.rec_id,
            status="APPROVED" if cmd.action == "approve" else "REJECTED",
            cert_id=cert_id,
        )
