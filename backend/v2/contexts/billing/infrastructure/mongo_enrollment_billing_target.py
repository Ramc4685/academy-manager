"""``EnrollmentBillingTargetReader`` over ``enrollments`` + ``sessions``.

Prices the enrollment through ``session_amount_cents`` and its active recurring
tuition discount — the same resolution the monthly generator uses — so a
hand-billed month charges what the automatic run would have charged.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId

from backend.v2.contexts.billing.application.use_cases.bill_enrollment_period import (
    EnrollmentBillingTarget,
)
from backend.v2.contexts.billing.domain.proration import BillingPeriod
from backend.v2.contexts.billing.domain.tuition_discount import (
    display_label,
    monthly_discount_cents,
    policy_applies_to_period,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    session_amount_cents,
)
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)
from backend.v2.shared.tenancy import current_academy_id


class MongoEnrollmentBillingTargetReader:
    def __init__(self, db: Any) -> None:
        self._db = db
        self._discounts = MongoTuitionDiscountRepository(db)

    async def load(self, enrollment_id: str, period: str) -> EnrollmentBillingTarget | None:
        academy_id = current_academy_id()
        enrollment = await self._db["enrollments"].find_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id}
        )
        if enrollment is None and ObjectId.is_valid(enrollment_id):
            enrollment = await self._db["enrollments"].find_one(
                {"academy_id": academy_id, "_id": ObjectId(enrollment_id)}
            )
        if enrollment is None:
            return None

        student_id = str(enrollment.get("student_id") or "")
        if not student_id:
            return None

        student = await self._db["students"].find_one(
            {"academy_id": academy_id, "student_id": student_id}
        )
        parent_id = str(
            enrollment.get("parent_id")
            or enrollment.get("parent_user_id")
            or (student or {}).get("parent_id")
            or (student or {}).get("parent_user_id")
            or ""
        )
        if not parent_id:
            return None

        session = await self._db["sessions"].find_one(
            {"academy_id": academy_id, "session_id": str(enrollment.get("session_id") or "")}
        )
        monthly_price_cents = max(session_amount_cents(session or {}), 0)
        discount_cents, discount_description, discount_id = await self._resolve_discount(
            enrollment_id=enrollment_id,
            monthly_price_cents=monthly_price_cents,
            period=period,
            timezone_name=str((session or {}).get("timezone") or "America/Chicago"),
        )
        return EnrollmentBillingTarget(
            enrollment_id=enrollment_id,
            academy_id=academy_id,
            student_id=student_id,
            parent_id=parent_id,
            monthly_price_cents=monthly_price_cents,
            status=str(enrollment.get("status") or ""),
            monthly_discount_cents=discount_cents,
            discount_description=discount_description,
            discount_id=discount_id,
        )

    async def _resolve_discount(
        self,
        *,
        enrollment_id: str,
        monthly_price_cents: int,
        period: str,
        timezone_name: str,
    ) -> tuple[int, str | None, str | None]:
        """The generator's recurring tuition discount for this enrollment/period.

        Mirrors ``_resolve_charge_for_enrollment``: the active policy is applied at
        monthly scale when its effective window overlaps the period, so the manual
        path and the cron agree on what the family owes for the month.
        """
        if monthly_price_cents <= 0:
            return 0, None, None
        policy = await self._discounts.get_active(enrollment_id)
        if policy is None:
            return 0, None, None
        billing_period = BillingPeriod.from_label(period, timezone_name=timezone_name)
        if not policy_applies_to_period(
            policy,
            period_start=billing_period.start_at.date(),
            period_end=billing_period.end_at.date(),
        ):
            return 0, None, None
        cents = monthly_discount_cents(policy, monthly_price_cents=monthly_price_cents)
        if cents <= 0:
            return 0, None, None
        label = display_label(policy)
        description = label if label.lower().endswith("discount") else f"{label} discount"
        return cents, description, policy.discount_id
