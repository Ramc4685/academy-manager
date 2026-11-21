"""Student-progress audit rows: ``certificate.revoked`` and the L5B share and settings changes."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.student_progress.domain.models import SkillCertificate
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoCertificateAuditLog(TenantScopedRepository):
    collection_name = "audit_logs"

    async def record_revoked(self, cert: SkillCertificate) -> bool:
        # A deterministic id makes the write an upsert, so a retry never doubles it.
        audit_id = f"certificate.revoked:{cert.cert_id}"
        result = await self._update_one(
            {"audit_id": audit_id},
            {
                "$setOnInsert": {
                    "actor_id": cert.revoked_by,
                    "action": "certificate.revoked",
                    "entity_type": "certificate",
                    "entity_id": cert.cert_id,
                    "reason": cert.revoke_reason,
                    "changed_keys": ["status"],
                    "before": {"status": "issued"},
                    "after": {"status": "revoked", "student_id": cert.student_id},
                    "created_at": cert.revoked_at or datetime.now(UTC),
                }
            },
            upsert=True,
        )
        return result.upserted_id is not None

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
        """One row per ``audit_id``: share links and progress settings changes (L5B)."""
        result = await self._update_one(
            {"audit_id": audit_id},
            {
                "$setOnInsert": {
                    "actor_id": actor_id,
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "changed_keys": sorted(k for k in after if before.get(k) != after.get(k)),
                    "before": before,
                    "after": after,
                    "created_at": at,
                }
            },
            upsert=True,
        )
        return result.upserted_id is not None
