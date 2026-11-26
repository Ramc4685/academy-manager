"""S40: one small port for "append a row to the academy audit trail".

Use cases in any context record their own audit row through this port; the
Mongo writer lives beside the other ``audit_logs`` writers in
``contexts/identity/infrastructure/mongo_audit_trail.py``. Audit rows here are
best effort: the action has already committed, so a failed audit write is
logged and never fails the action.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class AuditTrail(Protocol):
    async def append(
        self,
        *,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


async def record_best_effort(
    trail: AuditTrail | None,
    *,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if trail is None:
        return
    try:
        await trail.append(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
        )
    except Exception:
        log.exception("audit_append_failed", extra={"audit_action": action, "entity_id": entity_id})
