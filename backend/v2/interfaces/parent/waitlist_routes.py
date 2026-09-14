"""Parent-facing waitlist offer confirmation (issue #828).

A seat that opens is held for three days and the family is emailed. This is
where they say yes. The route is a thin shell over ``ConfirmWaitlistOffer``:
the ownership check, the deadline and the once-only guarantee all live in the
use case, because the same rules have to hold for any other caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import WaitlistOfferConfirmation
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.waitlist"])


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
