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
        # A deterministic id makes the write an upsert, so a retry never doubles
        # it. A re-placement on the same level that credits skills is its own row.
        audit_id = f"student.pathway_placed:{progress_id}"
        if credited_skill_ids:
            digest = hashlib.sha256(",".join(sorted(credited_skill_ids)).encode()).hexdigest()
            audit_id += f":{digest[:16]}"
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
