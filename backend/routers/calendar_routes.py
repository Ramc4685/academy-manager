"""Calendar events feed for FullCalendar — sessions expanded into weekly occurrences.
Returns a flat list of event objects with title/start/end/colour/extendedProps that
FullCalendar consumes directly. Role-scoped:
  • admin  — every active session
  • coach  — only sessions they are assigned to
  • parent — only sessions their child is enrolled in (approved & active)
"""
from datetime import datetime, timedelta, time, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from bson import ObjectId

from auth import get_current_user
from db import get_db

router = APIRouter()


_DAY_TO_WEEKDAY = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_SKILL_COLOR = {
    "beginner": "#22c55e",      # green
    "intermediate": "#2563eb",  # blue
    "advanced": "#facc15",      # yellow
}


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(s.split("T")[0] if "T" in s else s, "%Y-%m-%d")
        except Exception:
            continue
    return None


def _parse_time(s: str) -> time:
    if not s:
        return time(0, 0)
    try:
        h, m = s.split(":")[:2]
        return time(int(h), int(m))
    except Exception:
        return time(0, 0)


def _expand_session(session: dict, range_start: datetime, range_end: datetime, coach_name: str) -> list[dict]:
    """Expand a session into per-week occurrences within [range_start, range_end]."""
    sess_start = _parse_date(session.get("start_date", ""))
    sess_end = _parse_date(session.get("end_date", ""))
    if not sess_start or not sess_end:
        return []
    days = session.get("days_of_week") or []
    weekdays = {_DAY_TO_WEEKDAY[d.strip().lower()] for d in days if d.strip().lower() in _DAY_TO_WEEKDAY}
    if not weekdays:
        return []
    t_start = _parse_time(session.get("start_time", ""))
    t_end = _parse_time(session.get("end_time", ""))

    span_start = max(sess_start, range_start)
    span_end = min(sess_end, range_end)
    if span_start > span_end:
        return []

    color = _SKILL_COLOR.get((session.get("skill_level") or "").lower(), "#0f172a")
    sid = str(session["_id"])
    out: list[dict] = []
    cur = span_start
    while cur <= span_end:
        if cur.weekday() in weekdays:
            start_dt = datetime.combine(cur.date(), t_start)
            end_dt = datetime.combine(cur.date(), t_end)
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(hours=1)
            out.append({
                "id": f"{sid}_{cur.strftime('%Y%m%d')}",
                "title": session.get("name") or "Session",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "color": color,
                "textColor": "#0f172a" if color == "#facc15" else "#ffffff",
                "extendedProps": {
                    "session_id": sid,
                    "skill_level": session.get("skill_level"),
                    "location": session.get("location"),
                    "coach_name": coach_name,
                    "max_students": session.get("max_students"),
                    "monthly_price": session.get("monthly_price"),
                    "type": "session",
                },
            })
        cur += timedelta(days=1)
    return out


@router.get("/calendar/events")
async def calendar_events(
    start: str = Query(..., description="ISO date range start (FullCalendar fetch param)"),
    end: str = Query(..., description="ISO date range end (FullCalendar fetch param)"),
    user=Depends(get_current_user),
):
    db = get_db()
    range_start = _parse_date(start) or datetime.now(timezone.utc).replace(day=1)
    range_end = _parse_date(end) or (range_start + timedelta(days=60))

    q: dict = {"is_deleted": {"$ne": True}, "status": {"$ne": "cancelled"}}

    if user["role"] == "coach":
        q["coach_id"] = user["id"]
    elif user["role"] == "parent":
        # Build list of session_ids parent's kids are actively enrolled in
        enrolls = await db.enrollments.find({
            "parent_user_id": user["id"],
            "status": "active",
            "is_deleted": {"$ne": True},
            "approval_status": {"$nin": ["pending", "pending_payment"]},
        }).to_list(500)
        sess_ids = list({e["session_id"] for e in enrolls if e.get("session_id")})
        if not sess_ids:
            return []
        try:
            q["_id"] = {"$in": [ObjectId(x) for x in sess_ids]}
        except Exception:
            raise HTTPException(status_code=500, detail="Bad enrollment session id")
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    sessions = await db.sessions.find(q).to_list(500)
    coach_ids = {s.get("coach_id") for s in sessions if s.get("coach_id")}
    coach_names: dict[str, str] = {}
    if coach_ids:
        async for c in db.users.find({"_id": {"$in": [ObjectId(c) for c in coach_ids]}}):
            coach_names[str(c["_id"])] = c.get("name") or c.get("email") or "Coach"

    events: list[dict] = []
    for s in sessions:
        coach = coach_names.get(s.get("coach_id"), "Unassigned")
        events.extend(_expand_session(s, range_start, range_end, coach))

    return events
