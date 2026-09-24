"""Platform routes for tenant data export and purge dry-run (roadmap L9d).

Platform-admin only; anyone else gets 404, as on the other platform routes.
There is no purge-execution route: a purge is owner-confirmed and run by
hand, see docs/runbooks/tenant-export-and-purge.md.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.platform.application.use_cases.tenant_data_offboarding import (
    TenantDataOffboardingService,
)
from backend.v2.interfaces.platform.bootstrap_routes import require_platform_admin
from backend.v2.shared.auth.claims import AuthClaims

router = APIRouter(prefix="/platform", tags=["platform"])


class TenantDataExportRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is required")
        return stripped


class CollectionCountResponse(BaseModel):
    collection: str
    count: int


class PurgeDryRunResponse(BaseModel):
    academy_id: str
    tenant_status: str
    cancelled_at: datetime | None = None
    generated_at: datetime
    would_delete: list[CollectionCountResponse]
    would_retain: list[CollectionCountResponse]
    total_to_delete: int
    confirm_token: str
    executed: bool


def get_tenant_data_offboarding(request: Request) -> TenantDataOffboardingService:
    """The service is wired in the composition root (``main.py``)."""
    service = getattr(request.app.state, "tenant_data_offboarding", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Tenant data export is not configured")
    return service  # type: ignore[no-any-return]


def _content_disposition(filename: str) -> str:
    """Attachment header that cannot carry quotes, backslashes or CR/LF.

    The filename embeds the academy_id path parameter, so the plain
    ``filename=`` fallback is reduced to a safe ASCII allowlist and the exact
    name travels RFC 5987-encoded in ``filename*=``.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "tenant-export.zip"
    return f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    request_id = request.headers.get("x-request-id") or getattr(request.state, "request_id", None)
    return request_id, request.client.host if request.client else None


@router.post("/tenants/{academy_id}/data-export")
async def export_tenant_data(
    academy_id: str,
    payload: TenantDataExportRequest,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
    service: TenantDataOffboardingService = Depends(get_tenant_data_offboarding),
) -> Response:
    """Download a zip of every tenant-scoped collection for one academy."""
    request_id, ip_address = _request_meta(request)
    archive = await service.export_tenant(
        academy_id,
        actor_user_id=claims.user_id,
        reason=payload.reason,
        request_id=request_id,
        ip_address=ip_address,
    )
    return Response(
        content=archive.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(archive.filename),
            "X-Export-Sha256": archive.sha256,
            "Cache-Control": "no-store",
        },
    )


@router.post("/tenants/{academy_id}/purge-dry-run", response_model=PurgeDryRunResponse)
async def preview_tenant_purge(
    academy_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
    service: TenantDataOffboardingService = Depends(get_tenant_data_offboarding),
) -> PurgeDryRunResponse:
    """Counts of what a purge would delete. Deletes nothing; cancelled tenants only."""
    request_id, ip_address = _request_meta(request)
    result = await service.purge_dry_run(
        academy_id,
        actor_user_id=claims.user_id,
        request_id=request_id,
        ip_address=ip_address,
    )
    return PurgeDryRunResponse(**result.model_dump())
