"""Admin BFF: ``GET /admin/payments/collections`` — the Payments bucket view.

Spec: ``docs/superpowers/specs/2026-09-05-payments-buckets-design.md`` §3.

The reader is attached at ``app.state.admin_collections`` by
``composition/collections.py`` (``composition/admin.py`` is at its line
budget). This module only knows the reader's protocol.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, Depends, Query, Request

from backend.v2.interfaces.admin.collections_views import AdminCollectionsView
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

_PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class AdminCollectionsReader(Protocol):
    async def build(self, period: str | None = None, *, debug: bool = False) -> dict[str, Any]: ...


def get_admin_collections(request: Request) -> AdminCollectionsReader:
    reader: AdminCollectionsReader = request.app.state.admin_collections
    return reader


router = APIRouter(tags=["admin.collections"])


@router.get("/payments/collections", response_model=AdminCollectionsView)
async def payments_collections(
    period: str | None = Query(default=None, pattern=_PERIOD_PATTERN),
    debug: bool = Query(default=False),
    _claims: AuthClaims = Depends(require_persona("admin")),
    reader: AdminCollectionsReader = Depends(get_admin_collections),
) -> AdminCollectionsView:
    """Families grouped into the six collection buckets for one billing period.

    ``period`` defaults to the academy's current local month. ``debug`` adds
    the ``unclassified`` list (families whose facts could not be assembled).
    """
    view = await reader.build(period, debug=debug)
    return AdminCollectionsView.model_validate(view)
