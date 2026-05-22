"""Application ports for platform audit logging."""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.platform.audit.domain.models import PlatformAuditEvent


class PlatformAuditRepository(Protocol):
    """Persistence port for platform audit events."""

    async def append(self, event: PlatformAuditEvent) -> PlatformAuditEvent: ...

    async def list_events(
        self,
        *,
        academy_id: str | None = None,
        limit: int = 100,
    ) -> list[PlatformAuditEvent]: ...
