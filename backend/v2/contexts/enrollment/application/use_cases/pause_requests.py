"""Parent-requested enrollment pauses."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, model_validator

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    PauseEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferral,
    BillingDeferralRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound
from backend.v2.shared.ids import new_ulid

PauseRequestStatus = Literal["pending", "approved", "declined"]
PauseKind = Literal["fixed", "indefinite"]


def _period_from_resume_on(value: object) -> str:
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    if isinstance(value, str) and len(value) >= 7:
        return value[:7]
    return ""


class PauseRequest(BaseModel):
    model_config = {"frozen": True}

    pause_request_id: str
    enrollment_id: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    student_id: str | None = None
    student_name: str | None = None
    session_id: str | None = None
    session_title: str | None = None
    session_location: str | None = None
    session_start_at: datetime | None = None
    session_end_at: datetime | None = None
    period: str = ""
    pause_kind: PauseKind = "fixed"
    resume_on: date | None = None
    review_on: date | None = None
    reason: str = ""
    status: PauseRequestStatus = "pending"
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_pause_window(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        pause_kind = values.get("pause_kind") or "fixed"
        resume_on = values.get("resume_on")
        review_on = values.get("review_on")
        period = str(values.get("period") or "")
        if pause_kind == "indefinite":
            if resume_on is not None:
                raise ValueError("resume_on is only allowed for fixed pauses")
            if review_on is None:
                raise ValueError("review_on is required for indefinite pauses")
            if not period:
                values["period"] = _period_from_resume_on(review_on)
            values["pause_kind"] = pause_kind
            return values
        if resume_on is None:
            raise ValueError("resume_on is required for fixed pauses")
        if not period:
            values["period"] = _period_from_resume_on(resume_on)
        values["pause_kind"] = pause_kind
        return values


class PauseRequestRepository(Protocol):
    async def add(self, request: PauseRequest) -> None: ...
    async def get(self, pause_request_id: str) -> PauseRequest | None: ...
    async def list_for_parent(self, parent_id: str) -> list[PauseRequest]: ...
    async def list_pending(self) -> list[PauseRequest]: ...
    async def approve(self, pause_request_id: str, *, admin_id: str) -> PauseRequest: ...
    async def decline(self, pause_request_id: str, *, admin_id: str) -> PauseRequest: ...
    async def enrollment_belongs_to_parent(self, enrollment_id: str, parent_id: str) -> bool: ...


class PauseEnrollmentRunner(Protocol):
    async def execute(self, cmd: PauseEnrollmentCommand) -> None: ...


class ParentAutopayStateGateway(Protocol):
    """Cross-context port: toggle the parent's app-owned autopay enrollment
    status (Slice B). Replaces the retired Stripe-subscription-collection
    pause path — the pause request already carries `parent_id` directly.
    """

    async def set_enrollment_status(self, *, parent_id: str, status: str) -> None: ...


class RequestEnrollmentPauseCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    enrollment_id: str
    period: str = ""
    pause_kind: PauseKind = "fixed"
    resume_on: date | None = None
    review_on: date | None = None
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _validate_pause_window(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        pause_kind = values.get("pause_kind") or "fixed"
        resume_on = values.get("resume_on")
        review_on = values.get("review_on")
        period = str(values.get("period") or "")
        if pause_kind == "indefinite":
            if resume_on is not None:
                raise ValueError("resume_on is only allowed for fixed pauses")
            if review_on is None:
                raise ValueError("review_on is required for indefinite pauses")
            if not period:
                values["period"] = _period_from_resume_on(review_on)
            values["pause_kind"] = pause_kind
            return values
        if resume_on is None:
            raise ValueError("resume_on is required for fixed pauses")
        if not period:
            values["period"] = _period_from_resume_on(resume_on)
        values["pause_kind"] = pause_kind
        return values


class DecidePauseRequestCommand(BaseModel):
    model_config = {"frozen": True}

    pause_request_id: str
    admin_id: str


class RequestEnrollmentPause:
    def __init__(self, *, pause_requests: PauseRequestRepository) -> None:
        self._pause_requests = pause_requests

    async def execute(self, cmd: RequestEnrollmentPauseCommand) -> PauseRequest:
        belongs = await self._pause_requests.enrollment_belongs_to_parent(
            cmd.enrollment_id, cmd.parent_id
        )
        if not belongs:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        request = PauseRequest(
            pause_request_id=str(new_ulid()),
            enrollment_id=cmd.enrollment_id,
            parent_id=cmd.parent_id,
            period=cmd.period,
            pause_kind=cmd.pause_kind,
            resume_on=cmd.resume_on,
            review_on=cmd.review_on,
            reason=cmd.reason,
            created_at=datetime.now(UTC),
        )
        await self._pause_requests.add(request)
        return request


class ListParentPauseRequests:
    def __init__(self, *, pause_requests: PauseRequestRepository) -> None:
        self._pause_requests = pause_requests

    async def execute(self, parent_id: str) -> list[PauseRequest]:
        return await self._pause_requests.list_for_parent(parent_id)


class ListAdminPauseRequests:
    def __init__(self, *, pause_requests: PauseRequestRepository) -> None:
        self._pause_requests = pause_requests

    async def execute(self) -> list[PauseRequest]:
        return await self._pause_requests.list_pending()


class ApprovePauseRequest:
    def __init__(
        self,
        *,
        pause_requests: PauseRequestRepository,
        pause_enrollment: PauseEnrollmentRunner | None = None,
        scheduled_actions: ScheduledEnrollmentActionRepository | None = None,
        billing_deferrals: BillingDeferralRepository | None = None,
        parent_autopay: ParentAutopayStateGateway | None = None,
        academy_id: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._pause_requests = pause_requests
        self._pause_enrollment = pause_enrollment
        self._scheduled_actions = scheduled_actions
        self._billing_deferrals = billing_deferrals
        self._parent_autopay = parent_autopay
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: DecidePauseRequestCommand) -> PauseRequest:
        existing = await self._pause_requests.get(cmd.pause_request_id)
        if existing is not None and existing.status == "approved":
            return existing

        request = await self._pause_requests.approve(
            cmd.pause_request_id,
            admin_id=cmd.admin_id,
        )
        if self._pause_enrollment is not None:
            await self._pause_enrollment.execute(
                PauseEnrollmentCommand(
                    enrollment_id=request.enrollment_id,
                    actor_id=cmd.admin_id,
                    reason=request.reason or "parent pause request",
                    resume_on=request.resume_on,
                    review_on=request.review_on,
                    create_billing_deferral=False,
                    pause_stripe_collection=False,
                )
            )
        if self._billing_deferrals is not None:
            now = self._now()
            await self._billing_deferrals.add(
                BillingDeferral(
                    deferral_id=str(new_ulid()),
                    enrollment_id=request.enrollment_id,
                    student_id=request.student_id or "",
                    deferral_type="fixed_pause" if request.pause_kind == "fixed" else "admin_pause",
                    reason=request.reason or "parent pause request",
                    source="pause_request",
                    source_id=request.pause_request_id,
                    actor_id=cmd.admin_id,
                    actor_type="admin",
                    billing_period=request.period,
                    resume_on=request.resume_on,
                    review_on=request.review_on,
                    created_at=now,
                    updated_at=now,
                    metadata={"pause_kind": request.pause_kind},
                )
            )
        if self._parent_autopay is not None and request.parent_id:
            # App-owned autopay (Slice B): pause toggles autopay_enrollment_status
            # directly — there is no Stripe subscription collection to pause.
            await self._parent_autopay.set_enrollment_status(
                parent_id=request.parent_id,
                status="paused",
            )
        if (
            request.pause_kind == "fixed"
            and request.resume_on is not None
            and self._scheduled_actions is not None
        ):
            now = self._now()
            await self._scheduled_actions.add(
                ScheduledEnrollmentAction(
                    action_id=str(new_ulid()),
                    academy_id=self._academy_id or request.parent_id,
                    action_type="resume_from_pause",
                    enrollment_id=request.enrollment_id,
                    pause_request_id=request.pause_request_id,
                    run_at=datetime(
                        request.resume_on.year,
                        request.resume_on.month,
                        request.resume_on.day,
                        tzinfo=UTC,
                    ),
                    created_at=now,
                    updated_at=now,
                )
            )
        return request


class DeclinePauseRequest:
    def __init__(self, *, pause_requests: PauseRequestRepository) -> None:
        self._pause_requests = pause_requests

    async def execute(self, cmd: DecidePauseRequestCommand) -> PauseRequest:
        return await self._pause_requests.decline(
            cmd.pause_request_id,
            admin_id=cmd.admin_id,
        )
