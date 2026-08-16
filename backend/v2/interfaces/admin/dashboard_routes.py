"""Admin dashboard aggregation routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
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
log = logging.getLogger(__name__)


@router.get("/dashboard/attention", response_model=AdminAttentionList)
async def dashboard_attention(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAttentionList:
    """Aggregate dashboard attention signals from existing admin BFF sources."""

    items: list[AdminAttentionItemView] = []
    today = date.today()

    blocked_resume_reader = getattr(use_cases, "list_blocked_scheduled_resume_actions", None)

    # Fan out all independent data fetches concurrently.
    if callable(blocked_resume_reader):
        (
            dues_rows,
            pause_requests,
            blocked_resumes,
            billing_deferral_warnings,
            waiver_report,
            sessions,
        ) = await asyncio.gather(
            _read_attention_source("dues_followup", use_cases.list_dues_followup, []),
            _read_attention_source(
                "pause_requests", use_cases.list_admin_pause_requests.execute, []
            ),
            _read_attention_source("blocked_scheduled_resumes", blocked_resume_reader, []),
            _read_attention_source(
                "billing_deferral_warnings",
                use_cases.list_billing_deferral_warnings,
                [],
                today=today,
                limit=100,
            ),
            _read_attention_source("waivers", use_cases.list_admin_waivers.execute, None),
            _read_attention_source("sessions", use_cases.list_admin_sessions, [], today),
        )
    else:
        (
            dues_rows,
            pause_requests,
            billing_deferral_warnings,
            waiver_report,
            sessions,
        ) = await asyncio.gather(
            _read_attention_source("dues_followup", use_cases.list_dues_followup, []),
            _read_attention_source(
                "pause_requests", use_cases.list_admin_pause_requests.execute, []
            ),
            _read_attention_source(
                "billing_deferral_warnings",
                use_cases.list_billing_deferral_warnings,
                [],
                today=today,
                limit=100,
            ),
            _read_attention_source("waivers", use_cases.list_admin_waivers.execute, None),
            _read_attention_source("sessions", use_cases.list_admin_sessions, [], today),
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
                href="/admin/reports/dues",
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

    if billing_deferral_warnings:
        count = len(billing_deferral_warnings)
        high_count = len(
            [
                row
                for row in billing_deferral_warnings
                if str(_field(row, "severity", "medium")) == "high"
            ]
        )
        items.append(
            AdminAttentionItemView(
                attention_id="billing-deferral-risks",
                kind="billing_deferrals",
                title="Paused billing needs review",
                detail=(
                    f"{count} enrollment{'s' if count != 1 else ''} have paused billing "
                    "risk or legacy skip metadata."
                ),
                severity="high" if high_count else "medium",
                href="/admin/payments",
                count=count,
            )
        )

    waiver_count = (
        waiver_report.summary.pending_count + waiver_report.summary.outdated_count
        if waiver_report is not None
        else 0
    )
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


async def _read_attention_source(
    label: str,
    reader: Callable[..., Awaitable[Any]],
    default: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return await reader(*args, **kwargs)
    except Exception:
        log.warning("admin dashboard attention source unavailable: %s", label, exc_info=True)
        return default


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
