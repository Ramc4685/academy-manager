"""Platform support cancels a self-service account deletion (mobile M5, PR #1115).

Restore is support-only: academy admins cannot undo a person's own deletion
request, which covers every academy. Support confirms with the person, then
cancels the whole request here. Platform admin or platform support only;
anyone else gets 404, as on the other platform routes. Runbook:
docs/runbooks/account-deletion-support-restore.md.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.identity.application.use_cases.cancel_account_deletion import (
    CancelAccountDeletion,
)
from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.interfaces.platform.governance_routes import (
    _platform_role,
    require_platform_support,
)
from backend.v2.shared.auth.claims import AuthClaims

log = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["platform"])


class CancelAccountDeletionPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is required")
        return stripped


class CancelAccountDeletionResponse(BaseModel):
    request_id: str
    user_id: str
    academy_ids: list[str]
    firebase_enabled: bool


def get_cancel_account_deletion(request: Request) -> CancelAccountDeletion:
    use_case = getattr(request.app.state, "cancel_account_deletion", None)
    if use_case is None:
        raise HTTPException(status_code=503, detail="Account deletion is not configured")
    return use_case  # type: ignore[no-any-return]


@router.post("/account-deletions/{request_id}/cancel", response_model=CancelAccountDeletionResponse)
async def cancel_account_deletion(
    request_id: str,
    payload: CancelAccountDeletionPayload,
    request: Request,
    claims: AuthClaims = Depends(require_platform_support),
    use_case: CancelAccountDeletion = Depends(get_cancel_account_deletion),
) -> CancelAccountDeletionResponse:
    """Restore the account in every academy and re-enable its login."""
    result = await use_case.execute(request_id)
    cancelled = result.request
    audit = getattr(request.app.state, "platform_audit", None)
    if audit is not None:
        # One row per academy so each academy's audit listing shows it; logged,
        # not raised: the restore already happened and must be reported as such.
        for academy_id in cancelled.academy_ids or ("platform",):
            try:
                await audit.record_event(
                    RecordPlatformAuditEventCommand(
                        actor_user_id=claims.user_id,
                        actor_membership_id=claims.membership_id,
                        academy_id=academy_id,
                        platform_actor_role=_platform_role(claims),
                        action="account_deletion.cancelled_by_support",
                        entity_type="user",
                        entity_id=cancelled.user_id,
                        after_snapshot={
                            "request_id": cancelled.request_id,
                            "academy_ids": list(cancelled.academy_ids),
                            "firebase_enabled": result.firebase_enabled,
                            "reason": payload.reason,
                        },
                        request_id=request.headers.get("x-request-id")
                        or getattr(request.state, "request_id", None),
                        ip_address=request.client.host if request.client else None,
                    )
                )
            except Exception as exc:
                log.warning("platform_audit_emit_failed: %s", exc)
    return CancelAccountDeletionResponse(
        request_id=cancelled.request_id,
        user_id=cancelled.user_id,
        academy_ids=list(cancelled.academy_ids),
        firebase_enabled=result.firebase_enabled,
    )
