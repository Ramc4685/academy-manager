"""``GET /api/v2/calendar-feed/{token}.ics``: a parent's subscribed class calendar.

Not under ``interfaces/public``: that package is the anonymous academy page,
which may never carry family data (``test_public_page_dto_no_leak``). This is
a token-authenticated read of one family's own schedule, like the unsubscribe
links.

The token is the whole authority (no login: phone calendars cannot sign in).
Tenant comes from the request host, never the token, so a link opened on
another academy's host does not verify. Every failure — unknown host, bad
shape, wrong signature, a reset link, a parent who lost access — is the same
404. Rate limited per client IP across the whole prefix
(``shared/http/rate_limit.py``) so tokens cannot be walked.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from backend.v2.interfaces.public.academy_page_routes import not_found_response
from backend.v2.shared.tenancy.context import tenant_scope

router = APIRouter(prefix="/calendar-feed", tags=["calendar-feed"])


@router.get(
    "/{token}.ics",
    response_class=Response,
    responses={404: {"description": "No calendar for this link on this host."}},
)
async def get_calendar_feed(token: str, request: Request) -> Response:
    academy_id = getattr(request.state, "resolved_academy_id", None)
    parent = getattr(request.app.state, "parent", None)
    feed = getattr(parent, "calendar_feed", None)
    if not academy_id or feed is None or len(token) > 200:
        return not_found_response()
    with tenant_scope(str(academy_id)):
        body = await feed.render(token)
    if body is None:
        return not_found_response()
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            # A reset or a cancelled class must reach the phone on its next poll.
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="classes.ics"',
        },
    )
