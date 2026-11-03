"""Admin BFF: self-service account deletions in this academy (mobile M5, D4).

* ``GET /admin/account-deletions``: newest first, at most 200.

``require_persona("admin")``; the academy is the request's tenant. The
families list shows these rows and each family page shows a banner when its
parent id (or an alias of it) has a request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.v2.contexts.identity.application.use_cases.list_account_deletions import (
    ListAccountDeletions,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

router = APIRouter(tags=["admin.account_deletions"])


class AccountDeletionView(BaseModel):
    request_id: str
    user_id: str
    aliases: list[str]
    display_name: str
    status: Literal["scheduled", "completed"]
    requested_at: datetime
    execute_after: datetime
    completed_at: datetime | None
    attempts: int
    failing_step: str | None


class AccountDeletionList(BaseModel):
    deletions: list[AccountDeletionView]


def _use_case(request: Request) -> ListAccountDeletions:
    return request.app.state.list_account_deletions  # type: ignore[no-any-return]


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


@router.get("/account-deletions", response_model=AccountDeletionList)
async def list_account_deletions(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_case: ListAccountDeletions = Depends(_use_case),
) -> AccountDeletionList:
    rows = await use_case.execute(academy_id=_academy_id(claims))
    return AccountDeletionList(
        deletions=[
            AccountDeletionView(
                request_id=r.request_id,
                user_id=r.user_id,
                aliases=list(r.aliases),
                display_name=r.display_name,
                status=r.status,  # type: ignore[arg-type]
                requested_at=r.requested_at,
                execute_after=r.execute_after,
                completed_at=r.completed_at,
                attempts=r.attempts,
                failing_step=r.failing_step,
            )
            for r in rows
        ]
    )
