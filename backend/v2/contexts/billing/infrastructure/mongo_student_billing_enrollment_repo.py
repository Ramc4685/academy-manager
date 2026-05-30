"""Mongo StudentBillingEnrollmentRepository."""

from __future__ import annotations

from backend.v2.contexts.billing.domain.session_type import StudentBillingEnrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoStudentBillingEnrollmentRepository(TenantScopedRepository):
    collection_name = "student_billing_enrollments"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> StudentBillingEnrollment:
        return StudentBillingEnrollment(
            enrollment_id=str(doc["enrollment_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            parent_id=str(doc["parent_id"]),
            session_type_id=str(doc["session_type_id"]),
            stripe_subscription_id=doc.get("stripe_subscription_id"),  # type: ignore[arg-type]
            billing_start_date=doc["billing_start_date"],  # type: ignore[arg-type]
            status=doc.get("status", "active"),  # type: ignore[arg-type]
            override_price_cents=doc.get("override_price_cents"),  # type: ignore[arg-type]
            enrolled_at=doc["enrolled_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
        )

    async def save(self, enrollment: StudentBillingEnrollment) -> None:
        doc = enrollment.model_dump(mode="python")
        await self._update_one(
            {"enrollment_id": enrollment.enrollment_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, enrollment_id: str) -> StudentBillingEnrollment | None:
        doc = await self._find_one({"enrollment_id": enrollment_id})
        return self._to_domain(doc) if doc else None

    async def list_for_student(self, student_id: str) -> list[StudentBillingEnrollment]:
        cursor = self._find_many({"student_id": student_id}, sort=[("enrolled_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_parent(self, parent_id: str) -> list[StudentBillingEnrollment]:
        cursor = self._find_many({"parent_id": parent_id}, sort=[("enrolled_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def get_by_stripe_subscription(
        self, stripe_subscription_id: str
    ) -> StudentBillingEnrollment | None:
        doc = await self._find_one({"stripe_subscription_id": stripe_subscription_id})
        return self._to_domain(doc) if doc else None
