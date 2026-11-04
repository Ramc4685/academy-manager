"""Parent-facing waitlist offers (issue #828, X2).

A seat that opens is held for three days and the family is emailed. The email
lands on the parent Requests page, which reads ``GET /parent/waitlist`` and
answers with confirm or decline. The routes are thin shells over the use
cases: the ownership check, the deadline and the once-only guarantee all live
there, because the same rules have to hold for any other caller.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentWaitlistEntryView,
    ParentWaitlistList,
    WaitlistOfferConfirmation,
    WaitlistOfferDecline,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.waitlist"])


@router.get("/waitlist", response_model=ParentWaitlistList)
async def list_waitlist(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentWaitlistList:
    list_rows: Any = use_cases.list_parent_waitlist
    assert list_rows is not None  # wired by compose_parent
    rows = await list_rows(claims.user_id)
    return ParentWaitlistList(entries=[ParentWaitlistEntryView(**row) for row in rows])


@router.post("/waitlist/{waitlist_id}/confirm", response_model=WaitlistOfferConfirmation)
async def confirm_waitlist_offer(
    waitlist_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> WaitlistOfferConfirmation:
    confirm = use_cases.confirm_waitlist_offer
    assert confirm is not None  # wired by compose_parent
    enrollment_id = await confirm.execute(
        waitlist_id,
        # Scoped to the signed-in parent: the id travels in an email link, so
        # the use case refuses anybody else's offer as "not found".
        parent_id=claims.user_id,
        actor_id=claims.user_id,
    )
    return WaitlistOfferConfirmation(waitlist_id=waitlist_id, enrollment_id=enrollment_id)


@router.post("/waitlist/{waitlist_id}/decline", response_model=WaitlistOfferDecline)
async def decline_waitlist_offer(
    waitlist_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> WaitlistOfferDecline:
    decline = use_cases.decline_waitlist_offer
    assert decline is not None  # wired by compose_parent
    # Same ownership rule as confirm; the held seat goes to the next family.
    await decline.execute(waitlist_id, parent_id=claims.user_id)
    return WaitlistOfferDecline(waitlist_id=waitlist_id)
