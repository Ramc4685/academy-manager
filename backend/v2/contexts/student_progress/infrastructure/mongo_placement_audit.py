"""The ``student.pathway_placed`` audit row, written once per placement."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoPlacementAuditLog(TenantScopedRepository):
    collection_name = "audit_logs"

    async def record_placed(
        self,
        *,
        student_id: str,
        program_id: str,
        level_id: str,
        progress_id: str,
        placed_by: str,
        reason: str,
        credited_skill_ids: list[str],
    ) -> bool:
        # A deterministic id makes the write an upsert, so a retry of the same
        # request never doubles it. The id covers who placed, why and what was
        # credited, so another admin (or reason, or credit set) re-placing on the
        # same level is its own row; a new placement has a new progress_id.
        action = "\x1f".join([placed_by, reason, *sorted(credited_skill_ids)])
        digest = hashlib.sha256(action.encode()).hexdigest()[:16]
        audit_id = f"student.pathway_placed:{progress_id}:{digest}"
        credited = {"credited_skill_ids": credited_skill_ids} if credited_skill_ids else {}
        result = await self._update_one(
            {"audit_id": audit_id},
            {
                "$setOnInsert": {
                    "actor_id": placed_by,
                    "action": "student.pathway_placed",
                    "entity_type": "student",
                    "entity_id": student_id,
                    "reason": reason,
                    "changed_keys": ["program_id", "level_id", "progress_id", *credited],
                    "after": {
                        "program_id": program_id,
                        "level_id": level_id,
                        "progress_id": progress_id,
                        **credited,
                    },
                    "created_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        return result.upserted_id is not None
