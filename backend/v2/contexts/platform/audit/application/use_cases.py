"""Use cases for platform audit logging."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.platform.audit.application.ports import PlatformAuditRepository
from backend.v2.contexts.platform.audit.domain.models import PlatformAuditEvent
from backend.v2.shared.ids import new_ulid


class RecordPlatformAuditEventCommand(BaseModel):
    """Command for appending one immutable platform audit event."""

    actor_user_id: str = Field(min_length=1)
    actor_membership_id: str | None = None
    academy_id: str = Field(min_length=1)
    platform_actor_role: str | None = None
    action: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    request_id: str | None = None
    ip_address: str | None = None

    @field_validator(
        "actor_user_id",
        "actor_membership_id",
        "academy_id",
        "platform_actor_role",
        "action",
        "entity_type",
        "entity_id",
        "request_id",
        "ip_address",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ListPlatformAuditEventsQuery(BaseModel):
    """Query for platform audit event listing."""

    academy_id: str | None = None
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("academy_id")
    @classmethod
    def _strip_academy_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class PlatformAuditService:
    """Application service for recording and querying platform audit events."""

    def __init__(
        self,
        *,
        audit_events: PlatformAuditRepository,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._audit_events = audit_events
        self._id_factory = id_factory or (lambda: f"audit_{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def record_event(
        self,
        command: RecordPlatformAuditEventCommand,
    ) -> PlatformAuditEvent:
        event = PlatformAuditEvent(
            audit_event_id=self._id_factory(),
            actor_user_id=command.actor_user_id,
            actor_membership_id=command.actor_membership_id,
            academy_id=command.academy_id,
            platform_actor_role=command.platform_actor_role,
            action=command.action,
            entity_type=command.entity_type,
            entity_id=command.entity_id,
            before_snapshot=command.before_snapshot,
            after_snapshot=command.after_snapshot,
            request_id=command.request_id,
            ip_address=command.ip_address,
            created_at=self._clock(),
        )
        return await self._audit_events.append(event)

    async def list_events(
        self,
        query: ListPlatformAuditEventsQuery,
    ) -> list[PlatformAuditEvent]:
        return await self._audit_events.list_events(
            academy_id=query.academy_id,
            limit=query.limit,
        )
