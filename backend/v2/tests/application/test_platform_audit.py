"""Application tests for platform SaaS audit logging."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.platform.audit.application.use_cases import (
    ListPlatformAuditEventsQuery,
    PlatformAuditService,
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.audit.domain.models import PlatformAuditEvent


class FakePlatformAuditRepository:
    def __init__(self) -> None:
        self.events: list[PlatformAuditEvent] = []

    async def append(self, event: PlatformAuditEvent) -> PlatformAuditEvent:
        self.events.append(event)
        return event

    async def list_events(
        self,
        *,
        academy_id: str | None = None,
        limit: int = 100,
    ) -> list[PlatformAuditEvent]:
        events = self.events
        if academy_id is not None:
            events = [event for event in events if event.academy_id == academy_id]
        return sorted(events, key=lambda event: event.created_at, reverse=True)[:limit]


def _clock() -> datetime:
    return datetime(2026, 5, 22, 16, 0, tzinfo=UTC)


def _service(repo: FakePlatformAuditRepository) -> PlatformAuditService:
    return PlatformAuditService(
        audit_events=repo,
        id_factory=lambda: "audit_001",
        clock=_clock,
    )


def _record_command(**overrides: object) -> RecordPlatformAuditEventCommand:
    values: dict[str, object] = {
        "actor_user_id": "platform-admin",
        "actor_membership_id": None,
        "academy_id": "acad_blno",
        "platform_actor_role": "platform_admin",
        "action": "platform.tenant.suspended",
        "entity_type": "tenant",
        "entity_id": "acad_blno",
        "before_snapshot": {"status": "active"},
        "after_snapshot": {"status": "suspended", "status_reason": "billing"},
        "request_id": "req_123",
        "ip_address": "203.0.113.10",
    }
    values.update(overrides)
    return RecordPlatformAuditEventCommand(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_record_platform_audit_event_captures_required_saas_fields() -> None:
    repo = FakePlatformAuditRepository()

    event = await _service(repo).record_event(_record_command())

    assert event.audit_event_id == "audit_001"
    assert event.actor_user_id == "platform-admin"
    assert event.actor_membership_id is None
    assert event.academy_id == "acad_blno"
    assert event.platform_actor_role == "platform_admin"
    assert event.action == "platform.tenant.suspended"
    assert event.entity_type == "tenant"
    assert event.entity_id == "acad_blno"
    assert event.before_snapshot == {"status": "active"}
    assert event.after_snapshot == {"status": "suspended", "status_reason": "billing"}
    assert event.request_id == "req_123"
    assert event.ip_address == "203.0.113.10"
    assert event.created_at == _clock()
    assert repo.events == [event]


@pytest.mark.asyncio
async def test_audit_actions_cover_platform_launch_blocker_mutations() -> None:
    repo = FakePlatformAuditRepository()
    service = _service(repo)

    actions = [
        "platform.tenant.created",
        "platform.tenant.suspended",
        "platform.tenant.reactivated",
        "platform.tenant.cancelled",
        "platform.billing.subscription.activated",
        "platform.billing.subscription.cancelled",
        "platform.governance.tenant_export.requested",
        "platform.governance.tenant_deletion.requested",
        "platform.governance.student_data_deletion.requested",
        "platform.support_access.granted",
        "platform.support_access.revoked",
        "platform.support_impersonation.requested",
    ]

    for index, action in enumerate(actions):
        await service.record_event(
            _record_command(
                action=action,
                entity_type=action.split(".")[1],
                entity_id=f"entity_{index}",
            )
        )

    assert [event.action for event in repo.events] == actions


@pytest.mark.asyncio
async def test_tenant_scoped_audit_listing_does_not_leak_other_tenants() -> None:
    repo = FakePlatformAuditRepository()
    service = _service(repo)
    await service.record_event(_record_command(academy_id="acad_blno", entity_id="acad_blno"))
    await service.record_event(
        _record_command(
            academy_id="acad_other",
            entity_id="acad_other",
            request_id="req_other",
        )
    )

    scoped = await service.list_events(ListPlatformAuditEventsQuery(academy_id="acad_blno"))
    platform_wide = await service.list_events(ListPlatformAuditEventsQuery())

    assert [event.academy_id for event in scoped] == ["acad_blno"]
    assert {event.academy_id for event in platform_wide} == {"acad_blno", "acad_other"}


@pytest.mark.asyncio
async def test_platform_audit_listing_respects_limit() -> None:
    repo = FakePlatformAuditRepository()
    service = _service(repo)
    for index in range(3):
        await service.record_event(_record_command(entity_id=f"entity_{index}"))

    events = await service.list_events(ListPlatformAuditEventsQuery(limit=2))

    assert len(events) == 2
