"""``audit_logs`` rows for push tokens changing hands (mobile M2 hardening).

Same row shape as the other ``audit_logs`` writers (``MongoImportAuditLog``):
stamped with the tenant in scope, which is the academy the token moved INTO.
The row holds the token's fingerprint, never the token itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.communications.application.ports import PushTokenAudit
from backend.v2.contexts.communications.domain.push_device import PushTokenMove
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy.repository import TenantScopedRepository


class MongoPushTokenAudit(TenantScopedRepository, PushTokenAudit):
    collection_name = "audit_logs"

    async def record_token_moved(self, move: PushTokenMove) -> None:
        await self._insert_one(
            {
                "audit_id": new_ulid(),
                "actor_id": move.to_user_id,
                "action": "push_device.token_moved",
                "entity_type": "push_device",
                "entity_id": move.token_fingerprint,
                "reason": "push token registered by a different user or academy",
                "changed_keys": ["academy_id", "user_id"],
                "before": {"user_id": move.from_user_id, "academy_id": move.from_academy_id},
                "after": {"user_id": move.to_user_id, "academy_id": move.to_academy_id},
                "created_at": datetime.now(UTC),
            }
        )
