"""Admin BFF: the unified family timeline (People CRM spec §5, Phase 5; roadmap L4a/L4b).

``GET /admin/families/{parent_id}/timeline?before=<cursor>&limit=<n>``: one
newest-first feed of money, lifecycle, attendance, requests, comms, coach
notes, admin actions (an allowlist of ``audit_logs`` actions, with moved
family entries) and CRM notes, follow-ups and contacts. ``next_cursor`` is
null on the last page.

``require_persona("admin")`` (a coach or parent gets the wrong-persona 404,
docs/security-matrix.md); another academy's family, or no family, is a 404
(``Crm.FamilyNotFound``). Money amounts are gated here, once, by
``can_view_family_money`` (#553): a caller who may not see amounts gets every
money entry without ``amount_cents`` / ``refunded_cents`` and without the
dollar figures in its summary, and ``money_visible: false``.

The use case is ``app.state.admin_family_index.timeline``
(``composition/family_timeline.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.crm.application.money_visibility import can_view_family_money
from backend.v2.contexts.crm.application.timeline import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    TimelineCursor,
    TimelineEntry,
    redact_money,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

router = APIRouter(tags=["admin.families"])


def get_family_timeline(request: Request) -> Any:
    services = getattr(request.app.state, "admin_family_index", None)
    timeline = getattr(services, "timeline", None) if services is not None else None
    if timeline is None:
        raise HTTPException(status_code=503, detail="family timeline is not configured")
    return timeline


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


class FamilyTimelineEntryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    at: datetime
    kind: str
    code: str
    summary: str
    source: str
    detail: str | None = None
    student_id: str | None = None
    student_name: str | None = None
    enrollment_id: str | None = None
    invoice_id: str | None = None
    invoice_ids: list[str]
    actor_id: str | None = None
    actor_name: str | None = None
    reason: str | None = None
    amount_cents: int | None = None
    refunded_cents: int | None = None
    muted: bool
    collapsed_codes: list[str]


class FamilyTimelineView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_id: str
    entries: list[FamilyTimelineEntryView]
    next_cursor: str | None = None
    money_visible: bool
    warnings: list[str]


def _entry_view(e: TimelineEntry) -> FamilyTimelineEntryView:
    return FamilyTimelineEntryView(
        entry_id=e.entry_id,
        at=e.at,
        kind=e.kind,
        code=e.code,
        summary=e.summary,
        source=e.source,
        detail=e.detail,
        student_id=e.student_id,
        student_name=e.student_name,
        enrollment_id=e.enrollment_id,
        invoice_id=e.invoice_id,
        invoice_ids=list(e.invoice_ids),
        actor_id=e.actor_id,
        actor_name=e.actor_name,
        reason=e.reason,
        amount_cents=e.amount_cents,
        refunded_cents=e.refunded_cents,
        muted=e.muted,
        collapsed_codes=list(e.collapsed_codes),
    )


@router.get("/families/{parent_id}/timeline", response_model=FamilyTimelineView)
async def family_timeline(
    parent_id: str,
    before: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    claims: AuthClaims = Depends(require_persona("admin")),
    timeline: Any = Depends(get_family_timeline),
) -> FamilyTimelineView:
    """The family's unified timeline, newest first, one page at a time."""
    cursor: TimelineCursor | None = None
    if before:
        try:
            cursor = TimelineCursor.decode(before)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid timeline cursor") from exc
    page = await timeline.execute(
        academy_id=_academy_id(claims), parent_id=parent_id, before=cursor, limit=limit
    )
    money_visible = can_view_family_money(claims)
    entries = page.entries if money_visible else [redact_money(e) for e in page.entries]
    return FamilyTimelineView(
        family_id=page.family_id,
        entries=[_entry_view(e) for e in entries],
        next_cursor=page.next_cursor,
        money_visible=money_visible,
        warnings=page.warnings,
    )
