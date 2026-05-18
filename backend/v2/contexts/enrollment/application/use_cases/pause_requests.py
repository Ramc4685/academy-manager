"""Parent-requested enrollment pauses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, Field
from ulid import ULID

from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound


PauseRequestStatus = Literal["pending", "approved", "declined"]


class PauseRequest(BaseModel):
    model_config = {"frozen": True}

    pause_request_id: str
    enrollment_id: str
    parent_id: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    reason: str = ""
    status: PauseRequestStatus = "pending"
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class PauseRequestRepository(Protocol):
    async def add(self, request: PauseRequest) -> None: ...
    async def get(self, pause_request_id: str) -> PauseRequest | None: ...
    async def list_for_parent(self, parent_id: str) -> list[PauseRequest]: ...
    async def list_pending(self) -> list[PauseRequest]: ...
    async def approve(self, pause_request_id: str, *, admin_id: str) -> PauseRequest: ...
    async def decline(self, pause_request_id: str, *, admin_id: str) -> PauseRequest: ...
    async def enrollment_belongs_to_parent(self, enrollment_id: str, parent_id: str) -> bool: ...


class RequestEnrollmentPauseCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    enrollment_id: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    reason: str = ""


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
            pause_request_id=str(ULID()),
            enrollment_id=cmd.enrollment_id,
            parent_id=cmd.parent_id,
            period=cmd.period,
            reason=cmd.reason,
            created_at=datetime.now(timezone.utc),
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
    def __init__(self, *, pause_requests: PauseRequestRepository) -> None:
        self._pause_requests = pause_requests

    async def execute(self, cmd: DecidePauseRequestCommand) -> PauseRequest:
        return await self._pause_requests.approve(
            cmd.pause_request_id,
            admin_id=cmd.admin_id,
        )


class DeclinePauseRequest:
    def __init__(self, *, pause_requests: PauseRequestRepository) -> None:
        self._pause_requests = pause_requests

    async def execute(self, cmd: DecidePauseRequestCommand) -> PauseRequest:
        return await self._pause_requests.decline(
            cmd.pause_request_id,
            admin_id=cmd.admin_id,
        )
