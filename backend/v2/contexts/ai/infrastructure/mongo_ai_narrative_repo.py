"""``ai_narratives`` rows, tenant-scoped (migration 0224): one draft per
``(student_id, for_date, kind)``, held by the unique index."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.ai.domain.narrative import AiNarrative
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAiNarrativeRepository(TenantScopedRepository):
    collection_name = "ai_narratives"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> AiNarrative:
        # Mongo returns naive UTC datetimes; the domain row is tz-aware.
        return AiNarrative.model_validate(
            {
                k: v.replace(tzinfo=UTC) if isinstance(v, datetime) and v.tzinfo is None else v
                for k, v in doc.items()
                if k != "_id"
            }
        )

    async def upsert_draft(self, row: AiNarrative) -> AiNarrative:
        """A fresh draft replaces whatever row holds the key: the coach asked
        again, so the day's note starts over from the new text."""
        key = {"student_id": row.student_id, "for_date": row.for_date, "kind": row.kind}
        update = {"$set": row.model_dump(mode="python")}
        try:
            doc = await self._find_one_and_update(key, update, upsert=True)
        except DuplicateKeyError:
            # Two drafts raced on the unique key; the loser now matches the row.
            doc = await self._find_one_and_update(key, update, upsert=True)
        return self._to_domain(doc or row.model_dump(mode="python"))

    async def get(self, narrative_id: str) -> AiNarrative | None:
        doc = await self._find_one({"narrative_id": narrative_id})
        return self._to_domain(doc) if doc else None

    async def get_for(self, student_id: str, for_date: str, kind: str) -> AiNarrative | None:
        doc = await self._find_one({"student_id": student_id, "for_date": for_date, "kind": kind})
        return self._to_domain(doc) if doc else None

    async def list_pending(self, for_date: str, created_by: str | None) -> list[AiNarrative]:
        filter_: dict[str, Any] = {"status": "pending_review", "for_date": for_date}
        if created_by is not None:
            filter_["created_by"] = created_by
        cursor = self._find_many(filter_, sort=[("created_at", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def decide(
        self,
        narrative_id: str,
        *,
        status: Literal["approved", "rejected"],
        text: str | None,
        approver: str | None,
        decided_at: datetime,
    ) -> AiNarrative | None:
        fields: dict[str, Any] = {"status": status, "approver": approver, "decided_at": decided_at}
        if text is not None:
            fields["text"] = text
        doc = await self._find_one_and_update(
            {"narrative_id": narrative_id, "status": "pending_review"}, {"$set": fields}
        )
        return self._to_domain(doc) if doc else None

    async def approved_for(
        self, student_ids: list[str], for_date: str, kind: str
    ) -> dict[str, AiNarrative]:
        """Approved rows by student for the evening wins render; pending and
        rejected rows are simply absent, so the email never waits."""
        cursor = self._find_many(
            {
                "student_id": {"$in": student_ids},
                "for_date": for_date,
                "kind": kind,
                "status": "approved",
            }
        )
        return {str(doc["student_id"]): self._to_domain(doc) async for doc in cursor}
