"""Coach session announcement routes (#614).

GET    /coach/sessions/{session_id}/announcements
POST   /coach/sessions/{session_id}/announcements
DELETE /coach/sessions/{session_id}/announcements/{message_id}

Unassigned coach → 403 (checked before delegating, exactly as roster_routes.py,
feedback_routes.py and teaching_plan_routes.py do). Wrong persona → 404 via the
`require_persona` guard. Unauthenticated → 401.

The 403 is deliberate and is not a violation of the repo's "wrong persona is a
404" rule: that rule is about PERSONA, and a parent or admin hitting this route
still gets a 404. Assignment is authorization *within* the coach persona, and
every other coach session route already answers it with a 403.

A coach may delete only their own announcement; admin (through the admin
routes) may delete any.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.v2.composition.session_announcements import (
    AnnouncementDeleteForbidden,
    AnnouncementNotFound,
    SessionAnnouncementService,
    SessionNotFound,
)
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CoachSessionAnnouncementList,
    CoachSessionAnnouncementPostRequest,
    CoachSessionAnnouncementPostResponse,
    CoachSessionAnnouncementView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_lead_surface

router = APIRouter(tags=["coach.announcements"])

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN, detail="session not assigned to coach"
)
_NOT_AUTHOR = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="only the author or an admin may delete an announcement",
)
_SESSION_NOT_FOUND = HTTPException(status_code=404, detail="session not found")
_ANNOUNCEMENT_NOT_FOUND = HTTPException(status_code=404, detail="announcement not found")


async def _require_assigned(use_cases: CoachUseCases, coach_id: str, session_id: str) -> None:
    if not await use_cases.assigned_sessions.is_coach_assigned(  # type: ignore[attr-defined]
        coach_id, session_id
    ):
        raise _FORBIDDEN


def _service(use_cases: CoachUseCases) -> SessionAnnouncementService:
    service = use_cases.session_announcements
    if service is None:
        raise HTTPException(status_code=503, detail="Announcements are not configured")
    return service  # type: ignore[return-value]


def _view(message: object, viewer_id: str) -> CoachSessionAnnouncementView:
    return CoachSessionAnnouncementView(
        message_id=message.message_id,  # type: ignore[attr-defined]
        session_id=str(message.scope_id or ""),  # type: ignore[attr-defined]
        body=message.body,  # type: ignore[attr-defined]
        urgency=message.urgency,  # type: ignore[attr-defined]
        author_id=message.sender_id,  # type: ignore[attr-defined]
        author_display_name=message.author_display_name,  # type: ignore[attr-defined]
        author_persona=message.sender_persona,  # type: ignore[attr-defined]
        created_at=message.created_at,  # type: ignore[attr-defined]
        can_delete=message.sender_id == viewer_id,  # type: ignore[attr-defined]
    )


@router.get(
    "/sessions/{session_id}/announcements",
    response_model=CoachSessionAnnouncementList,
    summary="Announcements for an assigned session",
)
async def list_announcements(
    session_id: str,
    claims: AuthClaims = Depends(require_coach_lead_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachSessionAnnouncementList:
    await _require_assigned(use_cases, claims.user_id, session_id)
    try:
        messages = await _service(use_cases).list_for_session(session_id)
    except SessionNotFound as exc:
        raise _SESSION_NOT_FOUND from exc
    return CoachSessionAnnouncementList(announcements=[_view(m, claims.user_id) for m in messages])


@router.post(
    "/sessions/{session_id}/announcements",
    response_model=CoachSessionAnnouncementPostResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Post an announcement to an assigned session",
)
async def post_announcement(
    session_id: str,
    body: CoachSessionAnnouncementPostRequest,
    claims: AuthClaims = Depends(require_coach_lead_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachSessionAnnouncementPostResponse:
    await _require_assigned(use_cases, claims.user_id, session_id)
    try:
        result = await _service(use_cases).post(
            session_id=session_id,
            author_id=claims.user_id,
            author_persona="coach",
            body=body.body,
            urgent=body.urgent,
        )
    except SessionNotFound as exc:
        raise _SESSION_NOT_FOUND from exc
    return CoachSessionAnnouncementPostResponse(
        announcement=_view(result.message, claims.user_id),
        email_status=result.email_status,
        sent_count=result.sent_count,
        failed_count=result.failed_count,
    )


@router.delete(
    "/sessions/{session_id}/announcements/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete an announcement the coach authored",
)
async def delete_announcement(
    session_id: str,
    message_id: str,
    claims: AuthClaims = Depends(require_coach_lead_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> None:
    await _require_assigned(use_cases, claims.user_id, session_id)
    try:
        await _service(use_cases).delete(
            session_id=session_id,
            message_id=message_id,
            actor_id=claims.user_id,
            actor_is_admin=False,
        )
    except AnnouncementNotFound as exc:
        raise _ANNOUNCEMENT_NOT_FOUND from exc
    except AnnouncementDeleteForbidden as exc:
        raise _NOT_AUTHOR from exc
