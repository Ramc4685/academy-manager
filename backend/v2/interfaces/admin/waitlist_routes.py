"""Admin waitlist routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminGlobalWaitlistList,
    AdminGlobalWaitlistSessionView,
    AdminWaitlistEntry,
    AdminWaitlistList,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.waitlist"])


@router.get("/waitlist", response_model=AdminGlobalWaitlistList)
async def list_global_waitlist(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminGlobalWaitlistList:
    sessions = await use_cases.list_admin_sessions(None, window="upcoming")  # type: ignore[operator]
    grouped: list[AdminGlobalWaitlistSessionView] = []
    total = 0
    total_offered = 0
    for session in sessions:
        raw = session if isinstance(session, dict) else session.model_dump(exclude={"academy_id"})
        entries = await use_cases.list_waitlist_for_session(raw["session_id"])  # type: ignore[operator]
        normalized = _normalize_waitlist_entries(entries)
        if not normalized:
            continue
        offered = sum(1 for e in normalized if e.status == "offered")
        waiting = len(normalized) - offered
        total += waiting
        total_offered += offered
        grouped.append(
            AdminGlobalWaitlistSessionView(
                session_id=raw["session_id"],
                title=raw.get("title") or "Session",
                location=raw.get("location") or "",
                start_at=raw["start_at"],
                capacity=int(raw.get("capacity") or 0),
                enrolled_count=int(raw.get("enrolled_count") or 0),
                waitlist_count=int(raw.get("waitlist_count") or waiting),
                offered_count=offered,
                entries=normalized,
            )
        )
    return AdminGlobalWaitlistList(
        total_waitlisted=total, total_offered=total_offered, sessions=grouped
    )


@router.get(
    "/sessions/{session_id}/waitlist",
    response_model=AdminWaitlistList,
)
async def list_waitlist(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaitlistList:
    entries = await use_cases.list_waitlist_for_session(session_id)  # type: ignore[operator]
    normalized = _normalize_waitlist_entries(entries)
    return AdminWaitlistList(entries=normalized, waitlist=normalized)


def _normalize_waitlist_entries(entries: object) -> list[AdminWaitlistEntry]:
    rows = [
        e
        if isinstance(e, dict)
        else {
            "waitlist_id": e.waitlist_id,
            "session_id": e.session_id,
            "student_id": e.student_id,
            "parent_id": e.parent_id,
            "joined_at": e.joined_at,
            "added_at": e.joined_at,
            "status": e.status,
            "offer_expires_at": e.offer_expires_at,
        }
        for e in entries
    ]
    # X2: an ``offered`` row is holding a seat for a family that has not
    # answered. Filtering it out (as this did until X2) made the seat vanish
    # from every admin view. Offers lead; they have no queue position (0).
    offered = [row for row in rows if row.get("status") == "offered"]
    waiting = [row for row in rows if row.get("status") == "waiting"]
    positioned = [(0, row) for row in offered] + list(enumerate(waiting, start=1))
    return [
        AdminWaitlistEntry(
            **{
                **row,
                "position": position,
                "full_name": str(row.get("full_name") or "(unknown)"),
                "added_at": row.get("added_at") or row["joined_at"],
            }
        )
        for position, row in positioned
    ]


@router.post("/sessions/{session_id}/waitlist/promote", status_code=200)
async def promote_next(
    session_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, str | None]:
    promoted_id = await use_cases.promote_from_waitlist.execute(session_id, actor_id=claims.user_id)
    return {"promoted_waitlist_id": promoted_id}


@router.post("/waitlist/{waitlist_id}/skip", status_code=204, response_model=None)
async def skip(
    waitlist_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    if await _withdraw_offer(use_cases, waitlist_id, outcome="skipped"):
        return
    await use_cases.skip_from_waitlist.execute(waitlist_id)


@router.delete("/waitlist/{waitlist_id}", status_code=204, response_model=None)
async def remove(
    waitlist_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    if await _withdraw_offer(use_cases, waitlist_id, outcome="removed"):
        return
    await use_cases.remove_from_waitlist.execute(waitlist_id)


async def _withdraw_offer(use_cases: AdminUseCases, waitlist_id: str, *, outcome: str) -> bool:
    """Close an OFFERED row through the use case that gives its seat back.

    ``False`` for any other row, so Skip/Remove keep their plain status write.
    """
    withdraw = use_cases.withdraw_waitlist_offer
    if withdraw is None:
        return False
    return await withdraw.execute(waitlist_id, outcome=outcome)
