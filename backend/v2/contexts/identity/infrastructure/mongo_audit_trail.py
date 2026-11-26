"""Mongo writer for the ``AuditTrail`` port (S40): one ``audit_logs`` row.

Same row shape as ``MongoUserGovernanceAudit``; the academy is the request
tenant, read at write time, never captured at boot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id


class MongoAuditTrail:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def append(
        self,
        *,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        academy_id = current_academy_id()
        await self._db["audit_logs"].insert_one(
            {
                "audit_id": f"audit_{new_ulid()}",
                "academy_id": academy_id,
                "actor_id": actor_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "created_at": datetime.now(UTC),
                "metadata": metadata or {},
            }
        )
