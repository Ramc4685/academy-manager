"""Admin audit-log routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import AdminAuditLogList, AdminAuditLogView
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.audit"])


@router.get("/audit-logs", response_model=AdminAuditLogList)
async def list_audit_logs(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAuditLogList:
    rows = await use_cases.list_audit_logs()  # type: ignore[operator]
    return AdminAuditLogList(logs=[AdminAuditLogView(**row) for row in rows])
