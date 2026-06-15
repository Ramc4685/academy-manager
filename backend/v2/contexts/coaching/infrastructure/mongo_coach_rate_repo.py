"""Tenant-scoped Mongo repository for the ``coach_rates`` collection.

Write-side counterpart to the read-only rate lookup used by payout
computation (``composition.admin._MongoCoachRateRepository``). Indexes
live in migration 0102.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.coaching.domain.payout import CoachRate
from backend.v2.shared.tenancy import TenantScopedRepository


def _to_aware(dt: datetime | None) -> datetime | None:
    """Coerce a naive datetime from legacy Mongo docs to UTC-aware."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class MongoCoachRateRepository(TenantScopedRepository):
    collection_name = "coach_rates"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> CoachRate:
        return CoachRate(
            rate_id=str(doc.get("rate_id") or doc.get("_id")),
            academy_id=str(doc["academy_id"]),
            coach_id=str(doc["coach_id"]),
            billing_unit=doc.get("billing_unit", "per_session"),
            amount_minor=int(doc.get("amount_minor", doc.get("amount_cents", 0))),
            percent_bps=(None if doc.get("percent_bps") is None else int(doc["percent_bps"])),
            currency=str(doc.get("currency", "USD")).upper(),
            effective_from=_to_aware(doc["effective_from"]),
            effective_until=_to_aware(doc.get("effective_until")),
            status=doc.get("status", "active"),
        )

    async def list_for_coach(self, coach_id: str) -> list[CoachRate]:
        cursor = self._find_many(
            {"coach_id": coach_id},
            sort=[("effective_from", -1)],
            limit=200,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def find_active(self, coach_id: str) -> CoachRate | None:
        doc = await self._find_one_in_collection(
            self.collection_name,
            {"coach_id": coach_id, "status": "active"},
            sort=[("effective_from", -1)],
        )
        return self._to_domain(doc) if doc else None

    async def supersede(self, rate_id: str, *, effective_until: datetime) -> None:
        await self._update_one(
            {"rate_id": rate_id},
            {"$set": {"status": "superseded", "effective_until": effective_until}},
        )

    async def insert(self, rate: CoachRate) -> None:
        doc = {k: v for k, v in rate.model_dump(mode="python").items() if k != "academy_id"}
        await self._insert_one(doc)
