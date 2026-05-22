"""Platform audit routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.platform.audit.application.use_cases import (
    ListPlatformAuditEventsQuery,
    PlatformAuditService,
)
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims

router = APIRouter(prefix="/platform", tags=["platform-audit"])


class PlatformAuditEventResponse(BaseModel):
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


class PlatformAuditEventListResponse(BaseModel):
    events: list[PlatformAuditEventResponse] = Field(default_factory=list)


async def require_platform_audit_reader(
    claims: AuthClaims = Depends(get_auth_claims),
) -> AuthClaims:
    if not (claims.is_platform_admin() or claims.has_platform_role("platform_support")):
        raise HTTPException(status_code=404, detail="Not found")
    return claims


def get_platform_audit_service(request: Request) -> PlatformAuditService:
    service = getattr(request.app.state, "platform_audit", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Platform audit is not configured")
    return service  # type: ignore[no-any-return]


def _event_response(event: Any) -> PlatformAuditEventResponse:
    return PlatformAuditEventResponse(**event.model_dump())


@router.get("/audit-events", response_model=PlatformAuditEventListResponse)
async def list_platform_audit_events(
    academy_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthClaims = Depends(require_platform_audit_reader),
    service: PlatformAuditService = Depends(get_platform_audit_service),
) -> PlatformAuditEventListResponse:
    events = await service.list_events(
        ListPlatformAuditEventsQuery(academy_id=academy_id, limit=limit)
    )
    return PlatformAuditEventListResponse(events=[_event_response(event) for event in events])
