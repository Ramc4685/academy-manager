"""Mongo SkillCertificateRepository."""

from __future__ import annotations

from backend.v2.contexts.student_progress.domain.models import SkillCertificate
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSkillCertificateRepository(TenantScopedRepository):
    collection_name = "skill_certificates"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> SkillCertificate:
        return SkillCertificate(
            cert_id=str(doc["cert_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            program_id=str(doc["program_id"]),
            level_id=str(doc["level_id"]),
            cert_number=str(doc["cert_number"]),
            student_name=str(doc["student_name"]),
            level_name=str(doc["level_name"]),
            program_name=str(doc["program_name"]),
            completed_at=doc["completed_at"],
            issued_by=str(doc["issued_by"]),
            issued_at=doc["issued_at"],
        )

    async def save(self, cert: SkillCertificate) -> None:
        await self._insert_one(
            {
                "cert_id": cert.cert_id,
                "student_id": cert.student_id,
                "program_id": cert.program_id,
                "level_id": cert.level_id,
                "cert_number": cert.cert_number,
                "student_name": cert.student_name,
                "level_name": cert.level_name,
                "program_name": cert.program_name,
                "completed_at": cert.completed_at,
                "issued_by": cert.issued_by,
                "issued_at": cert.issued_at,
            }
        )

    async def list_for_student(self, student_id: str) -> list[SkillCertificate]:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("issued_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
