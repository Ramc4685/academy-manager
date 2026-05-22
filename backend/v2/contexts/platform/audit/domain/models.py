"""Platform audit domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class PlatformAuditEvent(BaseModel, frozen=True):
    """Immutable audit event for platform and support operations."""

    audit_event_id: str
    actor_user_id: str
    actor_membership_id: str | None = None
    academy_id: str
    platform_actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    request_id: str | None = None
    ip_address: str | None = None
    created_at: datetime

    @field_validator(
        "audit_event_id",
        "actor_user_id",
        "academy_id",
        "action",
        "entity_type",
        "entity_id",
    )
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field is required")
        return stripped
