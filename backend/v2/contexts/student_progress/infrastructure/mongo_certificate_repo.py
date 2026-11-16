"""Mongo SkillCertificateRepository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.contexts.student_progress.domain.models import SkillCertificate
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.time.mongo import ensure_utc

#: Rows from before 0234 have no status; they count as issued.
_NOT_REVOKED: dict[str, Any] = {"status": {"$ne": "revoked"}}
#: Account deletion drops these too: a revoke reason can name the child.
_ERASED_FIELDS = {"share_token": "", "revoke_reason": ""}


class MongoSkillCertificateRepository(TenantScopedRepository):
    collection_name = "skill_certificates"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> SkillCertificate:
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
            completed_at=ensure_utc(doc["completed_at"]),
            issued_by=str(doc["issued_by"]),
            issued_at=ensure_utc(doc["issued_at"]),
            status=doc.get("status") or "issued",
            revoked_at=ensure_utc(doc["revoked_at"]) if doc.get("revoked_at") else None,
            revoked_by=doc.get("revoked_by"),
            revoke_reason=doc.get("revoke_reason"),
            skill_names=doc.get("skill_names"),
            level_number=doc.get("level_number"),
            level_color=doc.get("level_color"),
            share_token=doc.get("share_token"),
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
                "status": cert.status,
                "skill_names": cert.skill_names,
                "level_number": cert.level_number,
                "level_color": cert.level_color,
            }
        )

    async def list_for_student(
        self, student_id: str, *, include_revoked: bool = False
    ) -> list[SkillCertificate]:
        filter_: dict[str, Any] = {"student_id": student_id}
        if not include_revoked:
            filter_ |= _NOT_REVOKED
        cursor = self._find_many(filter_, sort=[("issued_at", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_students(self, student_ids: list[str]) -> list[SkillCertificate]:
        if not student_ids:
            return []
        cursor = self._find_many(
            {"student_id": {"$in": student_ids}} | _NOT_REVOKED, sort=[("issued_at", 1)]
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_issued_between(self, start: datetime, end: datetime) -> list[SkillCertificate]:
        cursor = self._find_many({"issued_at": {"$gte": start, "$lt": end}} | _NOT_REVOKED)
        return [self._to_domain(doc) async for doc in cursor]

    async def revoke(
        self, student_id: str, cert_id: str, *, at: datetime, by: str, reason: str
    ) -> bool:
        result = await self._update_one(
            {"student_id": student_id, "cert_id": cert_id} | _NOT_REVOKED,
            {
                "$set": {
                    "status": "revoked",
                    "revoked_at": at,
                    "revoked_by": by,
                    "revoke_reason": reason,
                },
                "$unset": {"share_token": ""},
            },
        )
        return bool(result.modified_count)

    async def anonymise_student(self, student_id: str, *, student_name: str) -> None:
        """Account deletion: the child's name and revoke reason leave every certificate, and no link survives."""
        await self.collection.update_many(
            self._scoped({"student_id": student_id}),
            {"$set": {"student_name": student_name}, "$unset": _ERASED_FIELDS},
        )
