"""Parent self-enroll in a session type use cases.

EnrollChildInSessionType — parent enrolls their child in a session type,
creates a Stripe setup checkout session, persists the billing enrollment.

CancelBillingEnrollment — parent cancels their child's billing enrollment,
cancels the Stripe subscription at period end, and marks the enrollment cancelled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import (
    SessionTypeRepository,
    StripeGateway,
    StudentBillingEnrollmentRepository,
)
from backend.v2.contexts.billing.domain.errors import (
    SessionTypeInactive,
    SessionTypeNotFound,
    StudentBillingEnrollmentNotFound,
)
from backend.v2.contexts.billing.domain.session_type import StudentBillingEnrollment
from backend.v2.shared.ids import new_ulid


class StudentOwnerLookup(Protocol):
    """Port: verify that a student belongs to a given parent."""

    async def is_owned(self, parent_id: str, student_id: str) -> bool: ...


class EnrollChildCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    student_id: str
    session_type_id: str
    success_url: str
    cancel_url: str


class EnrollChildInSessionType:
    def __init__(
        self,
        *,
        enrollments: StudentBillingEnrollmentRepository,
        session_types: SessionTypeRepository,
        stripe: StripeGateway,
        student_owner_lookup: StudentOwnerLookup,
        academy_id: str,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._session_types = session_types
        self._stripe = stripe
        self._owner_lookup = student_owner_lookup
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: EnrollChildCommand) -> dict[str, Any]:
        # 1. Validate student ownership
        owned = await self._owner_lookup.is_owned(cmd.parent_id, cmd.student_id)
        if not owned:
            raise StudentBillingEnrollmentNotFound(
                "student not found or not owned by parent",
                student_id=cmd.student_id,
            )

        # 2. Validate session type exists and is active
        session_type = await self._session_types.get(cmd.session_type_id)
        if session_type is None:
            raise SessionTypeNotFound(
                "session type not found",
                session_type_id=cmd.session_type_id,
            )
        if not session_type.is_active:
            raise SessionTypeInactive(
                "session type is not active",
                session_type_id=cmd.session_type_id,
            )

        # 3. Create enrollment record
        enrollment_id = str(new_ulid())
        now = self._now()

        # 4. Start Stripe setup checkout so the app owns future invoices.
        (
            _checkout_id,
            redirect_url,
        ) = await self._stripe.create_autopay_setup_checkout_session(
            parent_id=cmd.parent_id,
            enrollment_id=enrollment_id,
            session_id=cmd.session_type_id,  # session_id field used as reference
            success_url=cmd.success_url,
            cancel_url=cmd.cancel_url,
            metadata={
                "academy_id": self._academy_id,
                "enrollment_id": enrollment_id,
                "parent_id": cmd.parent_id,
                "student_id": cmd.student_id,
                "session_type_id": cmd.session_type_id,
                "source": "autopay_setup",
            },
        )

        # 5. Persist enrollment with active status
        enrollment = StudentBillingEnrollment(
            enrollment_id=enrollment_id,
            academy_id=self._academy_id,
            student_id=cmd.student_id,
            parent_id=cmd.parent_id,
            session_type_id=cmd.session_type_id,
            stripe_subscription_id=None,
            billing_start_date=now,
            status="active",
            enrolled_at=now,
            updated_at=now,
        )
        await self._enrollments.save(enrollment)

        return {"enrollment": enrollment, "redirect_url": redirect_url}


class CancelBillingEnrollment:
    def __init__(
        self,
        *,
        enrollments: StudentBillingEnrollmentRepository,
        stripe: StripeGateway,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._stripe = stripe
        self._now = clock

    async def execute(self, *, parent_id: str, enrollment_id: str) -> StudentBillingEnrollment:
        # 1. Fetch and validate ownership
        enrollment = await self._enrollments.get(enrollment_id)
        if enrollment is None or enrollment.parent_id != parent_id:
            raise StudentBillingEnrollmentNotFound(
                "billing enrollment not found",
                enrollment_id=enrollment_id,
            )

        # 2. Short-circuit if already cancelled (idempotent)
        if enrollment.status == "cancelled":
            return enrollment  # idempotent — already cancelled

        # 3. Cancel Stripe subscription if present
        if enrollment.stripe_subscription_id:
            await self._stripe.cancel_subscription(
                enrollment.stripe_subscription_id,
                at_period_end=True,
            )

        # 4. Update status
        updated = enrollment.model_copy(update={"status": "cancelled", "updated_at": self._now()})
        await self._enrollments.save(updated)
        return updated
