"""``EnrollmentBillingTargetReader`` over ``enrollments`` + ``sessions``.

Prices the enrollment through ``resolve_monthly_charge`` — the monthly
generator's own resolver — so a hand-billed month charges what the automatic run
would have charged: first-month proration, the four-classes-per-meeting rule
(#721/#730), the active recurring tuition discount, and the
``billing_calculation_snapshots`` row later credits are measured against (#724).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from backend.v2.contexts.billing.application.use_cases.bill_enrollment_period import (
    BILLABLE_ENROLLMENT_STATUSES,
    EnrollmentBillingTarget,
)
from backend.v2.contexts.billing.domain.tuition_discount import display_label
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    resolve_monthly_charge,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
from backend.v2.shared.tenancy import current_academy_id


class MongoEnrollmentBillingTargetReader:
    def __init__(
        self, db: Any, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._db = db
        self._now = clock
        # The generator's resolver reads occurrences/discounts and writes the
        # calculation snapshot through this repo's storage-only methods; sharing it
        # is what keeps the manual and automatic prices identical.
        self._charges = MongoPaymentRepository(db, clock=clock)

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

        status = str(enrollment.get("status") or "")
        base = EnrollmentBillingTarget(
            enrollment_id=enrollment_id,
            academy_id=academy_id,
            student_id=student_id,
            parent_id=parent_id,
            monthly_price_cents=0,
            status=status,
        )
        if status not in BILLABLE_ENROLLMENT_STATUSES:
            # Resolving the charge stamps a CONSUMED first-month snapshot, which the
            # monthly run reads as "this month was already charged". Burning it for a
            # request the use case is about to refuse would zero out the family's real
            # invoice for the month, so an unbillable enrollment is never priced.
            return base

        session = await self._db["sessions"].find_one(
            {"academy_id": academy_id, "session_id": str(enrollment.get("session_id") or "")}
        )
        (
            gross_cents,
            discount_cents,
            _net_cents,
            snapshot_id,
            discount_policy,
            tuition_description,
        ) = await resolve_monthly_charge(
            repo=self._charges,
            enrollment=enrollment,
            session_doc=session or {},
            period=period,
            now=self._now(),
        )
        return base.model_copy(
            update={
                "monthly_price_cents": max(gross_cents, 0),
                "monthly_discount_cents": max(discount_cents, 0),
                "discount_description": _discount_description(discount_policy),
                "discount_id": discount_policy.discount_id if discount_policy else None,
                "tuition_description": tuition_description,
                "snapshot_id": snapshot_id,
            }
        )


def _discount_description(policy: Any | None) -> str | None:
    """The discount line's copy, worded as the monthly generator words it."""
    if policy is None:
        return None
    label = display_label(policy)
    return label if label.lower().endswith("discount") else f"{label} discount"
