"""``audit_logs`` row for an owner's change to the AI limits (L13)."""

from __future__ import annotations

from datetime import datetime

from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAiControlsAudit(TenantScopedRepository):
    collection_name = "audit_logs"

    async def record_changed(
        self,
        *,
        actor_id: str,
        before: dict[str, object],
        after: dict[str, object],
        at: datetime,
    ) -> None:
        await self._insert_one(
            {
                "audit_id": f"ai_controls.changed:{new_ulid()}",
                "actor_id": actor_id,
                "action": "ai_controls.changed",
                "entity_type": "academy_ai_controls",
                "entity_id": "ai",
                "changed_keys": sorted(k for k in after if before.get(k) != after.get(k)),
                "before": before,
                "after": after,
                "created_at": at,
            }
        )
