"""Admin BFF: the People CRM family index.

People CRM spec §3.2 and §7 Phase 2. Two read routes, both
``require_persona("admin")`` (spec §1: every CRM route):

* ``GET /admin/families``: search, scope/stage/class/card/overdue filters,
  sort (before pagination) and pagination over the academy's family index;
* ``GET /admin/families/summary``: the scope tiles over the unfiltered index;
* ``GET /admin/families/{family_id}/record``: one family's index row, the
  family record page's Overview header and Details (spec §4, Lane A4).

Services are attached at ``app.state.admin_family_index`` by
``composition/families_crm.py``. Every money field passes through
``can_view_family_money`` (the #553 staff-tier seam) here and nowhere else.
Declared before ``families_routes`` so the literal ``/families/summary`` can
never be read as a ``{parent_id}``.
"""

from __future__ import annotations

from typing import Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.v2.contexts.crm.application.family_index import (
    FAMILY_STAGES,
    FamilyIndex,
    FamilyIndexQuery,
    FamilyIndexUnavailable,
    find_family_record,
    normalize_stages,
    query_family_index,
    summarize_family_index,
)
from backend.v2.contexts.crm.application.money_visibility import can_view_family_money
from backend.v2.interfaces.admin.family_index_views import (
    AdminFamilyIndexPage,
    AdminFamilyIndexSummary,
    AdminFamilyRecordView,
    page_view,
    record_view,
    summary_view,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


class FamilyIndexReader(Protocol):
    async def build(self, academy_id: str) -> FamilyIndex: ...


class AdminFamilyIndexServices(Protocol):
    index: FamilyIndexReader


def get_admin_family_index(request: Request) -> AdminFamilyIndexServices:
    services: AdminFamilyIndexServices = request.app.state.admin_family_index
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


async def _index(services: AdminFamilyIndexServices, claims: AuthClaims) -> FamilyIndex:
    try:
        return await services.index.build(_academy_id(claims))
    except FamilyIndexUnavailable as exc:
        raise HTTPException(status_code=503, detail="family index unavailable") from exc


router = APIRouter(tags=["admin.families"])


@router.get("/families", response_model=AdminFamilyIndexPage)
async def list_families(
    search: str | None = Query(default=None, max_length=120),
    scope: Literal["active", "leaving", "left"] | None = None,
    stage: list[str] = Query(default_factory=list),
    class_id: str | None = Query(default=None, max_length=64),
    card_on_file: bool | None = None,
    overdue: bool | None = None,
    sort: Literal["name", "stage", "balance", "children"] = "name",
    order: Literal["asc", "desc"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamilyIndexServices = Depends(get_admin_family_index),
) -> AdminFamilyIndexPage:
    """The Families view: one row per family record."""
    stages = normalize_stages(stage)
    unknown = sorted(set(stages) - FAMILY_STAGES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown stage: {', '.join(unknown)}")
    index = await _index(services, claims)
    result = query_family_index(
        index,
        FamilyIndexQuery(
            search=search,
            scope=scope,
            stages=stages,
            class_id=class_id,
            card_on_file=card_on_file,
            overdue=overdue,
            sort=sort,
            descending=None if order is None else order == "desc",
            page=page,
            page_size=page_size,
        ),
        money_visible=can_view_family_money(claims),
    )
    return page_view(result, generated_at=index.generated_at)


@router.get("/families/summary", response_model=AdminFamilyIndexSummary)
async def family_index_summary(
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamilyIndexServices = Depends(get_admin_family_index),
) -> AdminFamilyIndexSummary:
    """Scope tiles (Active, Leaving, Left) over the unfiltered family index."""
    index = await _index(services, claims)
    return summary_view(
        summarize_family_index(index),
        generated_at=index.generated_at,
        money_visible=can_view_family_money(claims),
    )


@router.get("/families/{family_id}/record", response_model=AdminFamilyRecordView)
async def family_record(
    family_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamilyIndexServices = Depends(get_admin_family_index),
) -> AdminFamilyRecordView:
    """One family's index row: stage, children, contact, money (gated).

    404 when the id is not a family of this academy: the index is built from
    the caller's own tenant, so another academy's family is never found.
    """
    index = await _index(services, claims)
    record = find_family_record(index, family_id)
    if record is None:
        raise HTTPException(status_code=404, detail="family not found")
    return record_view(
        record,
        generated_at=index.generated_at,
        money_visible=can_view_family_money(claims),
        warnings=index.warnings,
    )
