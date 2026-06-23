"""Mongo repository for recurring tuition discount policies.

Stores one ``enrollment_discounts`` document per policy version. At most one row
per enrollment is ``active``; ``set_active`` supersedes the prior active row so
history is retained. All reads/writes are tenant-scoped via ``TenantScopedRepository``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount
from backend.v2.shared.tenancy import TenantScopedRepository


def _to_domain(doc: dict[str, Any]) -> TuitionDiscount:
    data = {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}
    return TuitionDiscount(**data)


class MongoTuitionDiscountRepository(TenantScopedRepository):
    collection_name = "enrollment_discounts"

    def __init__(
        self, db: Any, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        super().__init__(db)
        self._clock = clock

    async def set_active(
        self, policy: TuitionDiscount, *, set_by: str
    ) -> TuitionDiscount:
        now = self._clock()
        # Supersede any currently active policy for this enrollment.
        await self._update_one(
            {"enrollment_id": policy.enrollment_id, "status": "active"},
            {"$set": {"status": "superseded", "updated_at": now}},
        )
        doc = policy.model_dump(mode="json")
        doc.pop("academy_id", None)  # injected by _insert_one
        doc.update(status="active", set_by=set_by, set_at=now, updated_at=now)
        await self._insert_one(doc)
        saved = await self._find_one({"discount_id": policy.discount_id})
        assert saved is not None
        return _to_domain(saved)

    async def get_active(self, enrollment_id: str) -> TuitionDiscount | None:
        doc = await self._find_one(
            {"enrollment_id": enrollment_id, "status": "active"}
        )
        return _to_domain(doc) if doc else None

    async def active_by_enrollments(
        self, enrollment_ids: list[str]
    ) -> dict[str, TuitionDiscount]:
        if not enrollment_ids:
            return {}
        out: dict[str, TuitionDiscount] = {}
        cursor = self._find_many(
            {"enrollment_id": {"$in": enrollment_ids}, "status": "active"}
        )
        async for doc in cursor:
            out[str(doc["enrollment_id"])] = _to_domain(doc)
        return out

    async def remove(self, enrollment_id: str, *, ended_by: str) -> None:
        now = self._clock()
        await self._update_one(
            {"enrollment_id": enrollment_id, "status": "active"},
            {
                "$set": {
                    "status": "ended",
                    "ended_by": ended_by,
                    "ended_at": now,
                    "updated_at": now,
                }
            },
        )
