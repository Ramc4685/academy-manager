"""Admin BFF: ``POST /admin/reports/month-close/narrative`` (B5, paid, owner-only).

Owner only like the rest of ``/reports/*`` (listed in ``OWNER_ONLY_ROUTE_PATHS``,
non-owners get 404). The use case's own refusals pass through as domain
errors: 403 ``Ai.NotEntitled``, 429 ``Ai.MonthlyCapReached``, 503
``Ai.Disabled``, 502 ``Ai.ProviderError``. Nothing is stored but the
``ai_calls`` row; the owner reads the answer on the page.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.v2.contexts.ai.application.use_cases.narrate_month_close import (
    MonthCloseNarrative,
    NarrateMonthClose,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

_PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class AiReports(Protocol):
    """``composition/ai_reports.py::AiReportsComposition``."""

    narrate_month_close: NarrateMonthClose


def get_ai_reports(request: Request) -> AiReports | None:
    return getattr(request.app.state, "ai_reports", None)


router = APIRouter(tags=["admin.ai_reports"])


@router.post("/reports/month-close/narrative", response_model=MonthCloseNarrative)
async def month_close_narrative(
    period: str = Query(pattern=_PERIOD_PATTERN),
    claims: AuthClaims = Depends(require_owner()),
    comp: AiReports | None = Depends(get_ai_reports),
) -> MonthCloseNarrative:
    """What happened this month and what to fix first, written by the model
    from the month-close view and checked against it. The owner who asked is
    the approver on the ``ai_calls`` row."""
    if comp is None:
        raise HTTPException(status_code=503, detail="AI reports are unavailable")
    return await comp.narrate_month_close.execute(period=period, approver=claims.user_id)
