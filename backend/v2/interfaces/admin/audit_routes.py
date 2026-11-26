"""Admin audit-log routes (owner-only).

S39: the read is one merged, paginated trail over every audit collection,
composed in ``composition/audit_log.py`` and attached at
``app.state.admin_audit_log`` by ``main.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.v2.interfaces.admin.views import AdminAuditLogList, AdminAuditLogView
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

router = APIRouter(tags=["admin.audit"])


def get_admin_audit_log(request: Request) -> Any:
    return request.app.state.admin_audit_log


@router.get("/audit-logs", response_model=AdminAuditLogList)
async def list_audit_logs(
    actor_type: str | None = Query(
        default=None,
        description="Narrow the trail to one kind of actor: admin, owner, coach, parent, system.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(
        default=None, description="`next_cursor` from the previous page, for older rows."
    ),
    _claims: AuthClaims = Depends(require_owner()),
    audit_log: Any = Depends(get_admin_audit_log),
) -> AdminAuditLogList:
    try:
        page = await audit_log.list_page(actor_type=actor_type, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor.") from exc
    return AdminAuditLogList(
        logs=[AdminAuditLogView(**row) for row in page["logs"]],
        next_cursor=page["next_cursor"],
    )
