"""MongoHoldRepository — the reclaim CAS over ``held`` enrollment rows.

Operates on the same ``enrollments`` collection as ``MongoEnrollmentWriter``
but through a different predicate shape (session + status + unclaimed, with
a deterministic sort) — kept as its own repository per the ``HoldRepository``
Protocol, not folded into the enrollment writer. See the departures design
contract §3.4.
"""

from __future__ import annotations

from datetime import datetime

from pymongo import ASCENDING, ReturnDocument

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoHoldRepository(TenantScopedRepository):
    collection_name = "enrollments"

    async def claim_longest_held(
        self, *, session_id: str, now: datetime, requested_by: str
    ) -> Enrollment | None:
        doc = await self.collection.find_one_and_update(
            self._scoped(
                {
                    "session_id": session_id,
                    "status": "held",
                    "hold_reclaim_claimed_at": None,
                }
            ),
            {
                "$set": {
                    "status": "reclaim_pending",
                    "hold_reclaim_claimed_at": now,
                    "hold_reclaim_for": requested_by,
                    "updated_at": now,
                }
            },
            sort=[("hold_started_at", ASCENDING), ("enrollment_id", ASCENDING)],
            return_document=ReturnDocument.BEFORE,
        )
        return _to_domain(doc) if doc else None

    async def claim_expired(
        self, *, enrollment_id: str, now: datetime, requested_by: str
    ) -> Enrollment | None:
        # The expiry condition MUST be part of this CAS filter, not just the
        # `list_expired` snapshot that selected this row: between that
        # snapshot and this claim, the family can Return and be re-Held with
        # a fresh `hold_expires_at` (60 more days out). Filtering on
        # `status == "held"` alone still matches that re-held row and would
        # drop a family who is no longer overdue. Re-checking
        # `hold_expires_at <= now` here means the claim itself fails once the
        # row is no longer expired, exactly like `claim_longest_held` failing
        # once a row is no longer `status == "held"`.
        doc = await self._find_one_and_update(
            {
                "enrollment_id": enrollment_id,
                "status": "held",
                "hold_reclaim_claimed_at": None,
                "hold_expires_at": {"$lte": now},
            },
            {
                "$set": {
                    "status": "reclaim_pending",
                    "hold_reclaim_claimed_at": now,
                    "hold_reclaim_for": requested_by,
                    "updated_at": now,
                }
            },
            return_document_after=False,
        )
        return _to_domain(doc) if doc else None

    async def finalize_reclaim(
        self, enrollment_id: str, *, withdrawal_date: datetime
    ) -> Enrollment | None:
        doc = await self._find_one_and_update(
            {"enrollment_id": enrollment_id, "status": "reclaim_pending"},
            {
                "$set": {
                    "status": "withdrawn",
                    "withdrawal_date": withdrawal_date,
                    "updated_at": withdrawal_date,
                }
            },
            return_document_after=False,
        )
        return _to_domain(doc) if doc else None

    async def list_stalled(self, *, older_than: datetime) -> list[Enrollment]:
        cursor = self._find_many(
            {"status": "reclaim_pending", "hold_reclaim_claimed_at": {"$lt": older_than}}
        )
        return [_to_domain(doc) async for doc in cursor]

    async def list_due_for_reminder(self) -> list[Enrollment]:
        cursor = self._find_many({"status": "held"})
        return [_to_domain(doc) async for doc in cursor]

    async def list_expired(self, *, now: datetime) -> list[Enrollment]:
        cursor = self._find_many({"status": "held", "hold_expires_at": {"$lte": now}})
        return [_to_domain(doc) async for doc in cursor]


def _to_domain(doc: dict[str, object]) -> Enrollment:
    from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
        MongoEnrollmentWriter,
    )

    return MongoEnrollmentWriter._to_domain(doc)
