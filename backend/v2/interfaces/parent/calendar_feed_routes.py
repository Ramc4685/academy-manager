"""Parent phone-calendar subscription link.

``GET`` returns the parent's private ``webcal``-able URL (the same one every
time); ``POST .../reset`` makes a new one and kills every older link — for a
link the parent shared by mistake. 404 when the deployment has no signing
secret, so the portal simply hides the button.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.calendar-feed"])


class CalendarFeedLinkView(BaseModel):
    url: str


async def _link(use_cases: ParentUseCases, parent_id: str, *, reset: bool) -> CalendarFeedLinkView:
    feed = use_cases.calendar_feed
    url = await feed.feed_url(parent_id=parent_id, reset=reset) if feed is not None else None
    if url is None:
        raise HTTPException(status_code=404, detail="Calendar subscription is not available")
    return CalendarFeedLinkView(url=url)


@router.get("/calendar-feed", response_model=CalendarFeedLinkView)
async def get_calendar_feed_link(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> CalendarFeedLinkView:
    return await _link(use_cases, claims.user_id, reset=False)


@router.post("/calendar-feed/reset", response_model=CalendarFeedLinkView)
async def reset_calendar_feed_link(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> CalendarFeedLinkView:
    return await _link(use_cases, claims.user_id, reset=True)
