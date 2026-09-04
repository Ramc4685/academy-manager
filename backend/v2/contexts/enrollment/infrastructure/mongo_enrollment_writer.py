"""EnrollmentWriter."""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentWriter(TenantScopedRepository):
    collection_name = "enrollments"

    async def create(self, enrollment: Enrollment) -> None:
        doc = enrollment.model_dump(mode="python")
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def create_if_absent(self, enrollment: Enrollment) -> bool:
        """Atomically create a deterministic enrollment once.

        Registration approval can be submitted concurrently. The caller uses
        the boolean to release any duplicate seat reservation.
        """
        doc = enrollment.model_dump(mode="python")
        try:
            result = await self._update_one(
                {"enrollment_id": enrollment.enrollment_id},
                {"$setOnInsert": {k: v for k, v in doc.items() if k != "academy_id"}},
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return result.upserted_id is not None

    async def update_status(self, enrollment_id: str, status: str) -> None:
        await self._update_one({"enrollment_id": enrollment_id}, {"$set": {"status": status}})

    async def set_lifecycle_dates(
        self,
        enrollment_id: str,
        *,
        cancelled_at: datetime | None = None,
        withdrawal_date: datetime | None = None,
    ) -> None:
        """Persist the effective date of a cancel/withdraw (issue #651)."""
        fields: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if cancelled_at is not None:
            fields["cancelled_at"] = cancelled_at
            fields["cancelled_by"] = "admin"
        if withdrawal_date is not None:
            fields["withdrawal_date"] = withdrawal_date
        await self._update_one({"enrollment_id": enrollment_id}, {"$set": fields})

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

    async def mark_fee_billing_error(self, enrollment_id: str, *, error: str) -> None:
        """Targeted stamp of a failed self-cancel fee billing attempt onto
        the audit snapshot (admin-visibility rule: "Admin must see
        unrecovered failures"). Deliberately separate from
        ``mark_cancelled_by_parent`` — the CAS write already committed the
        cancellation; this is a best-effort follow-up write, not part of
        that atomic transition, and is intentionally unconditional (no CAS
        filter) since the enrollment is already cancelled by this point."""
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$set": {
                    "cancellation_policy_snapshot.fee_billing_error": error,
                    "updated_at": datetime.now(UTC),
                }
            },
        )

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

    async def add_skip_period(self, enrollment_id: str, period: str) -> None:
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$addToSet": {"skip_periods": period},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )

    async def set_enrolled_at_if_missing(self, enrollment_id: str, enrolled_at: datetime) -> None:
        await self._update_one(
            {
                "enrollment_id": enrollment_id,
                "$or": [{"enrolled_at": {"$exists": False}}, {"enrolled_at": None}],
            },
            {"$set": {"enrolled_at": enrolled_at, "updated_at": datetime.now(UTC)}},
        )

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Enrollment:
        return Enrollment(
            enrollment_id=str(doc["enrollment_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            status=doc.get("status", "active"),
            enrolled_at=doc.get("enrolled_at"),
            created_at=doc.get("created_at"),
            registration_application_id=doc.get("registration_application_id"),
            registration_student_lock=doc.get("registration_student_lock"),
            cancelled_by=doc.get("cancelled_by"),
            cancellation_reason=doc.get("cancellation_reason"),
            cancellation_policy_snapshot=doc.get("cancellation_policy_snapshot"),
            cancelled_at=doc.get("cancelled_at"),
        )

    async def get(self, enrollment_id: str) -> Enrollment | None:
        doc = await self._find_one({"enrollment_id": enrollment_id})
        return self._to_domain(doc) if doc else None

    async def list_cancelled_by_parent(self) -> list[Enrollment]:
        """Enrollments a parent self-cancelled (R4 admin audit list), newest
        ``cancelled_at`` first."""
        cursor = self._find_many({"cancelled_by": "parent"}, sort=[("cancelled_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def count_active_for_session(self, session_id: str) -> int:
        return await self.collection.count_documents(
            self._scoped({"session_id": session_id, "status": "active"})
        )

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
