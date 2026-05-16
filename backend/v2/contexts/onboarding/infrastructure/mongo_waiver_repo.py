"""Mongo WaiverRepository — returns the latest effective waiver."""

from __future__ import annotations

from backend.v2.contexts.onboarding.domain.models import Waiver
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoWaiverRepository(TenantScopedRepository):
    collection_name = "waivers"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Waiver:
        return Waiver(
            waiver_id=str(doc["waiver_id"]),
            academy_id=str(doc["academy_id"]),
            version=str(doc["version"]),
            text=str(doc["text"]),
            content_hash=str(doc["content_hash"]),
            effective_from=doc["effective_from"],  # type: ignore[arg-type]
        )

    async def get_active(self) -> Waiver | None:
        cursor = self._find_many({}, sort=[("effective_from", -1)], limit=1)
        async for doc in cursor:
            return self._to_domain(doc)
        return None
