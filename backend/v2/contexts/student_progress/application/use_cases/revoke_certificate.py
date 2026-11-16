"""Use case: the owner takes back a certificate issued in error.

The row stays (status ``revoked``) for the record; every non-admin read skips
it and its share link stops resolving. The student is not moved: if they earn
the level again, the approval issues a fresh certificate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.v2.contexts.student_progress.application.ports import CertificateRepository
from backend.v2.contexts.student_progress.domain.errors import (
    CertificateAlreadyRevoked,
    CertificateNotFound,
)
from backend.v2.contexts.student_progress.domain.models import SkillCertificate


@dataclass(frozen=True)
class RevokeCertificateCommand:
    student_id: str
    cert_id: str
    reason: str
    revoked_by: str


class RevokeCertificate:
    def __init__(self, *, certificates: CertificateRepository) -> None:
        self._certs = certificates

    async def execute(self, cmd: RevokeCertificateCommand) -> SkillCertificate:
        now = datetime.now(UTC)
        revoked = await self._certs.revoke(
            cmd.student_id, cmd.cert_id, at=now, by=cmd.revoked_by, reason=cmd.reason
        )
        cert = next(
            (
                c
                for c in await self._certs.list_for_student(cmd.student_id, include_revoked=True)
                if c.cert_id == cmd.cert_id
            ),
            None,
        )
        if cert is None:
            raise CertificateNotFound(
                "certificate not found", student_id=cmd.student_id, cert_id=cmd.cert_id
            )
        if not revoked:
            raise CertificateAlreadyRevoked("certificate is already revoked", cert_id=cmd.cert_id)
        return cert
