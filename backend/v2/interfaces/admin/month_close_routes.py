"""Admin BFF: ``GET /admin/reports/month-close`` — the Month close view.

Spec: ``docs/superpowers/specs/2026-09-07-month-close-design.md`` §4.

Owner only, like the rest of the Reports page: the route is listed in
``OWNER_ONLY_ROUTE_PATHS`` and the structural test checks both directions, so
a non-owner persona gets 404 and never 403.

The reader is attached at ``app.state.admin_month_close`` by
``composition/month_close.py`` (``composition/admin.py`` is at its line
budget). This module only knows the reader's protocol.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.v2.interfaces.admin.month_close_views import AdminMonthCloseView
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

_PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class AdminMonthCloseReader(Protocol):
    async def build(self, period: str | None = None) -> dict[str, Any]: ...


def get_admin_month_close(request: Request) -> AdminMonthCloseReader | None:
    return getattr(request.app.state, "admin_month_close", None)


router = APIRouter(tags=["admin.month_close"])


@router.get("/reports/month-close", response_model=AdminMonthCloseView)
async def reports_month_close(
    period: str | None = Query(default=None, pattern=_PERIOD_PATTERN),
    _claims: AuthClaims = Depends(require_owner()),
    reader: AdminMonthCloseReader | None = Depends(get_admin_month_close),
) -> AdminMonthCloseView:
    """The month's two runs, its money, and anything that looks wrong.

    ``period`` defaults to the academy's current local month.
    """
    if reader is None:
        raise HTTPException(status_code=503, detail="month close is unavailable")
    view = await reader.build(period)
    return AdminMonthCloseView.model_validate(view)
