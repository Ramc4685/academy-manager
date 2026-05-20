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
    for session in sessions:
        raw = session if isinstance(session, dict) else session.model_dump(exclude={"academy_id"})
        entries = await use_cases.list_waitlist_for_session(raw["session_id"])  # type: ignore[operator]
        normalized = _normalize_waitlist_entries(entries)
        if not normalized:
            continue
        total += len(normalized)
        grouped.append(
            AdminGlobalWaitlistSessionView(
                session_id=raw["session_id"],
                title=raw.get("title") or "Session",
                location=raw.get("location") or "",
                start_at=raw["start_at"],
                capacity=int(raw.get("capacity") or 0),
                enrolled_count=int(raw.get("enrolled_count") or 0),
                waitlist_count=int(raw.get("waitlist_count") or len(normalized)),
                entries=normalized,
            )
        )
    return AdminGlobalWaitlistList(total_waitlisted=total, sessions=grouped)


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
        }
        for e in entries
    ]
    return [
        AdminWaitlistEntry(
            **{
                **row,
                "position": int(row.get("position") or idx),
                "full_name": str(row.get("full_name") or "(unknown)"),
                "added_at": row.get("added_at") or row["joined_at"],
            }
        )
        for idx, row in enumerate(rows, start=1)
    ]


@router.post("/sessions/{session_id}/waitlist/promote", status_code=200)
async def promote_next(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, str | None]:
    promoted_id = await use_cases.promote_from_waitlist.execute(session_id)
    return {"promoted_waitlist_id": promoted_id}


@router.post("/waitlist/{waitlist_id}/skip", status_code=204, response_model=None)
async def skip(
    waitlist_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.skip_from_waitlist.execute(waitlist_id)


@router.delete("/waitlist/{waitlist_id}", status_code=204, response_model=None)
async def remove(
    waitlist_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.remove_from_waitlist.execute(waitlist_id)
