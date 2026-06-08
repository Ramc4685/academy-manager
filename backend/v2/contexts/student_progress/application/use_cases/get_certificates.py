"""Use case: get all certificates for a student."""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.student_progress.application.ports import CertificateRepository
from backend.v2.contexts.student_progress.domain.models import SkillCertificate


@dataclass(frozen=True)
class GetStudentCertificatesCommand:
    student_id: str


class GetStudentCertificates:
    def __init__(self, *, certificates: CertificateRepository) -> None:
        self._certs = certificates

    async def execute(self, cmd: GetStudentCertificatesCommand) -> list[SkillCertificate]:
        return await self._certs.list_for_student(cmd.student_id)
