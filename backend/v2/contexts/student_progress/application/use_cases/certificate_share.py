"""Parent opt-in share links for an issued certificate, and the public read (L5B).

``SetCertificateShare`` is the parent's switch. The route has already checked
the child is theirs (the student's own parent fields, in the request's
academy); this use case only ever touches that child's issued certificate.
Turning sharing on mints a random token once; turning it off drops it. Both
are idempotent (a repeat changes nothing and writes no audit row) and each
real change writes one audit row keyed by a digest of the token, never the
token itself.

``GetSharedCertificate`` is the anonymous read. The caller resolved the
academy from the request host and runs inside that tenant scope, so a token
only resolves within the academy whose host it was opened on. A revoked or
unknown token is ``None``: the route answers both with the same 404.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    ProgressAuditLog,
    ProgressSettingsStore,
)
from backend.v2.contexts.student_progress.domain.errors import CertificateNotFound
from backend.v2.contexts.student_progress.domain.milestones import share_recipient_name
from backend.v2.contexts.student_progress.domain.models import SkillCertificate

#: ``secrets.token_urlsafe(16)``: 22 URL-safe characters, 128 bits.
_TOKEN_BYTES = 16


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class SetCertificateShareCommand:
    student_id: str
    cert_id: str
    actor_id: str
    shared: bool


class SetCertificateShare:
    def __init__(
        self,
        *,
        certificates: CertificateRepository,
        audit: ProgressAuditLog,
    ) -> None:
        self._certs = certificates
        self._audit = audit

    async def _issued(self, student_id: str, cert_id: str) -> SkillCertificate:
        cert = next(
            (c for c in await self._certs.list_for_student(student_id) if c.cert_id == cert_id),
            None,
        )
        if cert is None:
            raise CertificateNotFound(
                "certificate not found", student_id=student_id, cert_id=cert_id
            )
        return cert

    async def execute(self, cmd: SetCertificateShareCommand) -> SkillCertificate:
        cert = await self._issued(cmd.student_id, cmd.cert_id)
        if cmd.shared and not cert.share_token:
            token = secrets.token_urlsafe(_TOKEN_BYTES)
            if await self._certs.set_share_token(cmd.student_id, cmd.cert_id, token):
                await self._write_audit(cmd, "certificate.share_created", token)
        elif not cmd.shared and cert.share_token:
            if await self._certs.clear_share_token(cmd.student_id, cmd.cert_id):
                await self._write_audit(cmd, "certificate.share_revoked", cert.share_token)
        # Re-read: a concurrent request may have won either race.
        return await self._issued(cmd.student_id, cmd.cert_id)

    async def _write_audit(self, cmd: SetCertificateShareCommand, action: str, token: str) -> None:
        shared = action == "certificate.share_created"
        await self._audit.record(
            audit_id=f"{action}:{cmd.cert_id}:{_digest(token)}",
            action=action,
            actor_id=cmd.actor_id,
            entity_type="certificate",
            entity_id=cmd.cert_id,
            before={"shared": not shared},
            after={"shared": shared, "student_id": cmd.student_id},
            at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class SharedCertificate:
    """Everything the public share page may show, and nothing else."""

    recipient_name: str
    level_name: str
    level_number: int | None
    level_color: str | None
    cert_number: str
    issued_at: datetime


class GetSharedCertificate:
    def __init__(
        self, *, certificates: CertificateRepository, settings: ProgressSettingsStore
    ) -> None:
        self._certs = certificates
        self._settings = settings

    async def execute(self, token: str) -> SharedCertificate | None:
        cert = await self._certs.get_issued_by_share_token(token)
        if cert is None or cert.status != "issued":
            return None
        rule = (await self._settings.get()).share_name
        return SharedCertificate(
            recipient_name=share_recipient_name(cert.student_name, rule),
            level_name=cert.level_name,
            # Issue-time snapshot only: a later curriculum edit never changes a shared page.
            level_number=cert.level_number,
            level_color=cert.level_color,
            cert_number=cert.cert_number,
            issued_at=cert.issued_at,
        )
