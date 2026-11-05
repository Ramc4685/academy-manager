"""Admin BFF: the roster-import copilot (plan 2026-11-04 Phase 2, slice B2).

* ``POST /admin/imports/families/map-columns`` with ``{filename?, csv}``,
  the same body and size guard as the import preview: asks the model for a
  column mapping and answers the draft plus ``sample_mode`` (``masked`` or
  ``values``) and ``prompt_version``. Writes nothing but the ``ai_calls``
  row; the frontend rewrites the CSV and the existing preview and commit
  stay the approval gate. ``require_persona("admin")``.
* ``GET`` and ``PUT /admin/ai/import-sharing`` ``{share_values}``: the
  academy's "let the model see real spreadsheet values" switch
  (``ai.share_import_values``). ``require_owner``, listed in
  ``OWNER_ONLY_ROUTE_PATHS``.

AI off (the default) surfaces as 503 ``Ai.Disabled`` from the shared error
handler; the month at its cap as 429 ``Ai.MonthlyCapReached``; an answer
that cannot be read as 502 ``Ai.ProviderError``.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.ai.application.use_cases.map_import_columns import ColumnMappingDraft
from backend.v2.interfaces.admin.family_import_routes import _parse_preview, _read_body
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner, require_persona

router = APIRouter(tags=["admin.imports"])


def get_ai_import(request: Request) -> Any:
    services = getattr(request.app.state, "ai_import", None)
    if services is None:
        raise HTTPException(status_code=503, detail="AI import help is not configured")
    return services


class MapColumnsResponse(ColumnMappingDraft):
    sample_mode: Literal["masked", "values"]
    prompt_version: str


class ImportSharingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_values: bool


@router.post("/imports/families/map-columns", response_model=MapColumnsResponse)
async def map_import_columns(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_ai_import),
) -> MapColumnsResponse:
    body = _parse_preview(await _read_body(request))
    result = await services.map_columns.execute(csv_text=body.csv, approver=claims.user_id)
    return MapColumnsResponse(
        **result.draft.model_dump(),
        sample_mode=result.sample_mode,
        prompt_version=result.prompt_version,
    )


@router.get("/ai/import-sharing", response_model=ImportSharingView)
async def get_import_sharing(
    claims: AuthClaims = Depends(require_owner()),
    services: Any = Depends(get_ai_import),
) -> ImportSharingView:
    return ImportSharingView(share_values=await services.sharing.share_values())


@router.put("/ai/import-sharing", response_model=ImportSharingView)
async def set_import_sharing(
    body: ImportSharingView,
    claims: AuthClaims = Depends(require_owner()),
    services: Any = Depends(get_ai_import),
) -> ImportSharingView:
    await services.sharing.set_share_values(body.share_values)
    return ImportSharingView(share_values=await services.sharing.share_values())
