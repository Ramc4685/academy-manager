"""Admin dashboard aggregation routes."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminAttentionItemView,
    AdminAttentionList,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.dashboard"])


@router.get("/dashboard/attention", response_model=AdminAttentionList)
async def dashboard_attention(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAttentionList:
    """Aggregate dashboard attention signals from existing admin BFF sources."""

    items: list[AdminAttentionItemView] = []

    blocked_resume_reader = getattr(use_cases, "list_blocked_scheduled_resume_actions", None)

    # Fan out all independent data fetches concurrently.
    if callable(blocked_resume_reader):
        dues_rows, pause_requests, blocked_resumes, waiver_report, sessions = await asyncio.gather(
            use_cases.list_dues_followup(),  # type: ignore[operator]
            use_cases.list_admin_pause_requests.execute(),
            blocked_resume_reader(),
            use_cases.list_admin_waivers.execute(),
            use_cases.list_admin_sessions(date.today()),  # type: ignore[operator]
        )
    else:
        dues_rows, pause_requests, waiver_report, sessions = await asyncio.gather(
            use_cases.list_dues_followup(),  # type: ignore[operator]
            use_cases.list_admin_pause_requests.execute(),
            use_cases.list_admin_waivers.execute(),
            use_cases.list_admin_sessions(date.today()),  # type: ignore[operator]
        )
        blocked_resumes: list[Any] = []

    overdue_count = len([row for row in dues_rows if int(row.get("total_due_cents") or 0) > 0])
    if overdue_count:
        items.append(
            AdminAttentionItemView(
                attention_id="overdue-dues",
                kind="overdue_dues",
                title="Overdue dues",
                detail=f"{overdue_count} parent account{'s' if overdue_count != 1 else ''} need follow-up.",
                severity="high",
                href="/admin/dues",
                count=overdue_count,
            )
        )

    pending_pauses = [row for row in pause_requests if getattr(row, "status", "") == "pending"]
    if pending_pauses:
        items.append(
            AdminAttentionItemView(
                attention_id="pending-pause-requests",
                kind="pause_requests",
                title="Pending pause requests",
                detail=f"{len(pending_pauses)} request{'s' if len(pending_pauses) != 1 else ''} awaiting approval.",
                severity="medium",
                href="/admin/pause-requests",
                count=len(pending_pauses),
            )
        )

    if blocked_resumes:
        count = len(blocked_resumes)
        items.append(
            AdminAttentionItemView(
                attention_id="scheduled-resume-blocked",
                kind="scheduled_resume_blocked",
                title="Scheduled resume blocked",
                detail=(
                    f"{count} enrollment{'s' if count != 1 else ''} could not resume "
                    "because the class is full."
                ),
                severity="medium",
                href="/admin/pause-requests",
                count=count,
            )
        )

    waiver_count = waiver_report.summary.pending_count + waiver_report.summary.outdated_count
    if waiver_count:
        items.append(
            AdminAttentionItemView(
                attention_id="waiver-status",
                kind="waivers",
                title="Waivers need review",
                detail=(
                    f"{waiver_report.summary.pending_count} pending, "
                    f"{waiver_report.summary.outdated_count} outdated."
                ),
                severity="medium",
                href="/admin/waivers",
                count=waiver_count,
            )
        )

    pressured = [p for p in (_session_pressure(s) for s in sessions) if p is not None]
    if pressured:
        items.append(
            AdminAttentionItemView(
                attention_id="session-pressure",
                kind="session_pressure",
                title="Session pressure",
                detail=f"{len(pressured)} session{'s' if len(pressured) != 1 else ''} full or waitlisted today.",
                severity="low",
                href="/admin/sessions",
                count=len(pressured),
            )
        )

    return AdminAttentionList(items=items)


def _field(session: Any, name: str, default: Any = None) -> Any:
    if isinstance(session, dict):
        return session.get(name, default)
    return getattr(session, name, default)


def _session_pressure(session: Any) -> str | None:
    enrolled = int(_field(session, "enrolled_count", 0) or 0)
    waitlist = int(_field(session, "waitlist_count", 0) or 0)
    capacity = int(_field(session, "capacity", 0) or 0)
    if waitlist > 0:
        return "waitlisted"
    if capacity > 0 and enrolled >= capacity:
        return "full"
    return None
