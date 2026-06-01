"""Session-type billing admin use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import (
    SessionTypeRepository,
    StripeGateway,
    StudentBillingEnrollmentRepository,
)
from backend.v2.contexts.billing.domain.errors import (
    SessionTypeNotFound,
    StudentBillingEnrollmentNotFound,
)
from backend.v2.contexts.billing.domain.session_type import (
    BillingPeriodType,
    SessionType,
    StudentBillingEnrollment,
)
from backend.v2.contexts.billing.domain.session_type_proration import (
    SessionTypeMoveProrationPolicy,
    SessionTypeMoveProrationResult,
)
from backend.v2.shared.ids import new_ulid


class SessionTypeChangeEventSink(Protocol):
    async def record_session_type_changed(
        self,
        *,
        academy_id: str,
        enrollment_id: str,
        student_id: str,
        parent_id: str,
        from_session_type_id: str | None,
        to_session_type_id: str,
        net_cents: int,
        actor_id: str,
        reason: str | None,
    ) -> None: ...


class CreateSessionTypeCommand(BaseModel):
    model_config = {"frozen": True}

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price_cents: int = Field(ge=0)
    billing_period: BillingPeriodType = "monthly"
    overage_rate_cents: int | None = Field(default=None, ge=0)


class UpdateSessionTypeCommand(BaseModel):
    model_config = {"frozen": True}

    session_type_id: str
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price_cents: int | None = Field(default=None, ge=0)
    billing_period: BillingPeriodType | None = None
    overage_rate_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class MoveStudentSessionTypeCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    to_session_type_id: str
    move_date: datetime
    period_start: datetime
    period_end: datetime
    actor_id: str
    reason: str | None = Field(default=None, max_length=500)


class PreviewStudentSessionTypeMoveCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    to_session_type_id: str
    move_date: datetime
    period_start: datetime
    period_end: datetime


class MoveStudentSessionTypeResult(BaseModel):
    model_config = {"frozen": True}

    enrollment: StudentBillingEnrollment
    proration: SessionTypeMoveProrationResult
    stripe_invoice_id: str | None = None


class OverrideStudentPriceCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    override_price_cents: int | None = Field(default=None, ge=0)


class CreateSessionType:
    def __init__(
        self,
        *,
        session_types: SessionTypeRepository,
        academy_id: str,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._session_types = session_types
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: CreateSessionTypeCommand) -> SessionType:
        now = self._now()
        session_type = SessionType(
            session_type_id=str(new_ulid()),
            academy_id=self._academy_id,
            name=cmd.name,
            description=cmd.description,
            price_cents=cmd.price_cents,
            billing_period=cmd.billing_period,
            overage_rate_cents=cmd.overage_rate_cents,
            created_at=now,
            updated_at=now,
        )
        await self._session_types.save(session_type)
        return session_type


class ListSessionTypes:
    def __init__(self, *, session_types: SessionTypeRepository) -> None:
        self._session_types = session_types

    async def execute(self) -> list[SessionType]:
        return await self._session_types.list_active()


class UpdateSessionType:
    def __init__(
        self,
        *,
        session_types: SessionTypeRepository,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._session_types = session_types
        self._now = clock

    async def execute(self, cmd: UpdateSessionTypeCommand) -> SessionType:
        existing = await self._session_types.get(cmd.session_type_id)
        if existing is None:
            raise SessionTypeNotFound("session type not found", session_type_id=cmd.session_type_id)
        updates = cmd.model_dump(exclude_unset=True, exclude={"session_type_id"})
        updated = existing.model_copy(update={**updates, "updated_at": self._now()})
        await self._session_types.save(updated)
        return updated


class SoftDeleteSessionType:
    def __init__(self, *, session_types: SessionTypeRepository) -> None:
        self._session_types = session_types

    async def execute(self, session_type_id: str) -> None:
        existing = await self._session_types.get(session_type_id)
        if existing is None:
            raise SessionTypeNotFound("session type not found", session_type_id=session_type_id)
        await self._session_types.soft_delete(session_type_id)


class ListStudentBillingEnrollments:
    def __init__(self, *, enrollments: StudentBillingEnrollmentRepository) -> None:
        self._enrollments = enrollments

    async def execute(
        self, *, student_id: str | None = None, parent_id: str | None = None
    ) -> list[StudentBillingEnrollment]:
        if student_id:
            return await self._enrollments.list_for_student(student_id)
        if parent_id:
            return await self._enrollments.list_for_parent(parent_id)
        return []


class OverrideStudentPrice:
    def __init__(
        self,
        *,
        enrollments: StudentBillingEnrollmentRepository,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._now = clock

    async def execute(self, cmd: OverrideStudentPriceCommand) -> StudentBillingEnrollment:
        existing = await self._enrollments.get(cmd.enrollment_id)
        if existing is None:
            raise StudentBillingEnrollmentNotFound(
                "billing enrollment not found",
                enrollment_id=cmd.enrollment_id,
            )
        updated = existing.model_copy(
            update={
                "override_price_cents": cmd.override_price_cents,
                "updated_at": self._now(),
            }
        )
        await self._enrollments.save(updated)
        return updated


class PreviewStudentSessionTypeMove:
    def __init__(
        self,
        *,
        enrollments: StudentBillingEnrollmentRepository,
        session_types: SessionTypeRepository,
        proration_policy: SessionTypeMoveProrationPolicy | None = None,
    ) -> None:
        self._enrollments = enrollments
        self._session_types = session_types
        self._policy = proration_policy or SessionTypeMoveProrationPolicy()

    async def execute(
        self, cmd: PreviewStudentSessionTypeMoveCommand
    ) -> SessionTypeMoveProrationResult:
        existing = await self._enrollments.get(cmd.enrollment_id)
        if existing is None:
            raise StudentBillingEnrollmentNotFound(
                "billing enrollment not found",
                enrollment_id=cmd.enrollment_id,
            )
        from_type = await self._session_types.get(existing.session_type_id)
        to_type = await self._session_types.get(cmd.to_session_type_id)
        if to_type is None:
            raise SessionTypeNotFound(
                "target session type not found",
                session_type_id=cmd.to_session_type_id,
            )

        return self._policy.quote(
            from_session_type=from_type,
            to_session_type=to_type,
            move_date=cmd.move_date,
            period_start=cmd.period_start,
            period_end=cmd.period_end,
        )


class MoveStudentSessionType:
    def __init__(
        self,
        *,
        enrollments: StudentBillingEnrollmentRepository,
        session_types: SessionTypeRepository,
        stripe: StripeGateway,
        event_sink: SessionTypeChangeEventSink,
        clock=lambda: datetime.now(UTC),
        proration_policy: SessionTypeMoveProrationPolicy | None = None,
    ) -> None:
        self._enrollments = enrollments
        self._session_types = session_types
        self._stripe = stripe
        self._event_sink = event_sink
        self._now = clock
        self._policy = proration_policy or SessionTypeMoveProrationPolicy()

    async def execute(self, cmd: MoveStudentSessionTypeCommand) -> MoveStudentSessionTypeResult:
        existing = await self._enrollments.get(cmd.enrollment_id)
        if existing is None:
            raise StudentBillingEnrollmentNotFound(
                "billing enrollment not found",
                enrollment_id=cmd.enrollment_id,
            )
        from_type = await self._session_types.get(existing.session_type_id)
        to_type = await self._session_types.get(cmd.to_session_type_id)
        if to_type is None:
            raise SessionTypeNotFound(
                "target session type not found",
                session_type_id=cmd.to_session_type_id,
            )

        proration = self._policy.quote(
            from_session_type=from_type,
            to_session_type=to_type,
            move_date=cmd.move_date,
            period_start=cmd.period_start,
            period_end=cmd.period_end,
        )
        stripe_invoice_id = None
        effective_price = existing.override_price_cents or to_type.price_cents
        if existing.stripe_subscription_id:
            stripe_invoice_id = await self._stripe.update_subscription_proration(
                existing.stripe_subscription_id,
                new_price_cents=effective_price,
                billing_period_start=cmd.period_start,
                billing_period_end=cmd.period_end,
            )
        updated = existing.model_copy(
            update={
                "session_type_id": to_type.session_type_id,
                "status": "active",
                "updated_at": self._now(),
            }
        )
        await self._enrollments.save(updated)
        await self._event_sink.record_session_type_changed(
            academy_id=updated.academy_id,
            enrollment_id=updated.enrollment_id,
            student_id=updated.student_id,
            parent_id=updated.parent_id,
            from_session_type_id=existing.session_type_id,
            to_session_type_id=updated.session_type_id,
            net_cents=proration.net_cents,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
        )
        return MoveStudentSessionTypeResult(
            enrollment=updated,
            proration=proration,
            stripe_invoice_id=stripe_invoice_id,
        )
