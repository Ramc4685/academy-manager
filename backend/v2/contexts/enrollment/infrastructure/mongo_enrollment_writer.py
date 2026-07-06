"""EnrollmentWriter."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentWriter(TenantScopedRepository):
    collection_name = "enrollments"

    async def create(self, enrollment: Enrollment) -> None:
        doc = enrollment.model_dump(mode="python")
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def update_status(self, enrollment_id: str, status: str) -> None:
        await self._update_one({"enrollment_id": enrollment_id}, {"$set": {"status": status}})

    async def mark_withdrawn(self, enrollment_id: str, *, withdrawal_date: datetime) -> None:
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$set": {
                    "status": "withdrawn",
                    "withdrawal_date": withdrawal_date,
                    "updated_at": datetime.now(UTC),
                }
            },
        )

    async def mark_cancelled_by_parent(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        cancellation_policy_snapshot: dict[str, object],
        cancelled_at: datetime,
    ) -> Enrollment | None:
        """Atomically transition active -> cancelled for a parent self-cancel
        (R4). Mirrors ``mark_withdrawn`` but, unlike it, uses the CAS helper
        (``_find_one_and_update`` filtered on ``status: "active"``) so a
        double-submitted cancel can't both succeed — the loser gets ``None``
        back and the use case raises ``EnrollmentNotCancellable``. Always
        stamps the full audit trail in the same write — never a silent
        state change.
        """
        doc = await self._find_one_and_update(
            {"enrollment_id": enrollment_id, "status": "active"},
            {
                "$set": {
                    "status": "cancelled",
                    "cancelled_by": "parent",
                    "cancellation_reason": cancellation_reason,
                    "cancellation_policy_snapshot": cancellation_policy_snapshot,
                    "cancelled_at": cancelled_at,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        return self._to_domain(doc) if doc else None

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        existing = await self._find_one({"enrollment_id": enrollment_id})
        previous_session_id = existing.get("session_id") if existing else None
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$set": {"session_id": session_id},
                "$push": {
                    "move_history": {
                        "from_session_id": previous_session_id,
                        "to_session_id": session_id,
                        "moved_at": datetime.now(UTC),
                    }
                },
            },
        )

    async def update_amount_cents(self, enrollment_id: str, amount_cents: int | None) -> None:
        update: dict[str, object]
        if amount_cents is None:
            update = {
                "$unset": {
                    "amount_cents": "",
                    "gross_amount_cents": "",
                    "final_amount_cents": "",
                    "monthly_price_cents": "",
                    "price_cents": "",
                },
                "$set": {"updated_at": datetime.now(UTC)},
            }
        else:
            update = {
                "$set": {
                    "amount_cents": amount_cents,
                    "gross_amount_cents": amount_cents,
                    "final_amount_cents": amount_cents,
                    "updated_at": datetime.now(UTC),
                }
            }
        await self._update_one({"enrollment_id": enrollment_id}, update)

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Enrollment:
        return Enrollment(
            enrollment_id=str(doc["enrollment_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            status=doc.get("status", "active"),  # type: ignore[arg-type]
            cancelled_by=doc.get("cancelled_by"),  # type: ignore[arg-type]
            cancellation_reason=doc.get("cancellation_reason"),  # type: ignore[arg-type]
            cancellation_policy_snapshot=doc.get("cancellation_policy_snapshot"),  # type: ignore[arg-type]
            cancelled_at=doc.get("cancelled_at"),  # type: ignore[arg-type]
        )

    async def get(self, enrollment_id: str) -> Enrollment | None:
        doc = await self._find_one({"enrollment_id": enrollment_id})
        return self._to_domain(doc) if doc else None

    async def list_cancelled_by_parent(self) -> list[Enrollment]:
        """Enrollments a parent self-cancelled (R4 admin audit list), newest
        ``cancelled_at`` first."""
        cursor = self._find_many({"cancelled_by": "parent"}, sort=[("cancelled_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        base_filter = {"session_id": session_id, "student_id": student_id}
        doc = await self._find_one({**base_filter, "status": "active"})
        if doc is None:
            doc = await self._find_one({**base_filter, "status": {"$exists": False}})
        if doc is None:
            doc = await self._find_one({**base_filter, "status": "paused"})
        if doc is None:
            doc = await self._find_one(base_filter)
        return self._to_domain(doc) if doc else None
