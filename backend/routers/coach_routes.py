"""Coach-facing daily operations endpoints.

Phase 5 Slice 7 launch-blocker: GET /api/coach/today returns the sessions
assigned to the authenticated coach on the requested academy-local date,
with a roster carrying only coach-relevant flags. Payment status is
intentionally hidden here so coaches do not see billing risk.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request

from auth import get_current_user
from db import get_db
from services.enrollment_service import APPROVED_ENROLLMENT_APPROVAL_STATUS

router = APIRouter(prefix="/coach", tags=["coach"])


_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _academy_tz() -> ZoneInfo:
    name = os.environ.get("SCHEDULER_TZ") or os.environ.get("ACADEMY_TIMEZONE", "America/Chicago")
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Chicago")


def _academy_today(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


def _to_object_id(value: str) -> Optional[ObjectId]:
    try:
        return ObjectId(value)
    except Exception:
        return None


@router.get("/today")
async def coach_today(
    request: Request,
    date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    # NOTE: any client-supplied coach_id query param is intentionally ignored;
    # the authenticated user's id is the only authoritative source.
    if user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Forbidden")

    tz = _academy_tz()
    tz_name = os.environ.get("SCHEDULER_TZ") or os.environ.get("ACADEMY_TIMEZONE", "America/Chicago")

    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format; expected YYYY-MM-DD")
        date_str = date
    else:
        date_str = _academy_today(tz)
        target = datetime.strptime(date_str, "%Y-%m-%d").date()

    weekday_name = _WEEKDAY_NAMES[target.weekday()]
    coach_id = user["id"]

    db = get_db()

    # Sessions assigned to this coach whose recurrence covers the requested date.
    sess_cursor = db.sessions.find({
        "coach_id": coach_id,
        "is_deleted": {"$ne": True},
        "status": {"$ne": "cancelled"},
    })
    sessions_raw = await sess_cursor.to_list(500)

    sessions_out = []
    for s in sessions_raw:
        start_date = s.get("start_date")
        end_date = s.get("end_date")
        if start_date and date_str < start_date:
            continue
        if end_date and date_str > end_date:
            continue
        days = s.get("days_of_week") or []
        if days and weekday_name not in days:
            continue

        session_id = str(s["_id"])

        # Active enrollments for this session.
        enroll_cursor = db.enrollments.find({
            "session_id": session_id,
            "status": "active",
            "approval_status": APPROVED_ENROLLMENT_APPROVAL_STATUS,
            "is_deleted": {"$ne": True},
        })
        enrollments = await enroll_cursor.to_list(500)
        student_ids = [e["student_id"] for e in enrollments]

        students_by_id: dict = {}
        if student_ids:
            obj_ids = [oid for oid in (_to_object_id(sid) for sid in student_ids) if oid is not None]
            if obj_ids:
                async for stu in db.students.find({"_id": {"$in": obj_ids}}):
                    students_by_id[str(stu["_id"])] = stu

        # Active pause requests on these enrollments.
        enrollment_ids = [str(e["_id"]) for e in enrollments]
        target_period = date_str[:7]
        paused_enrollment_ids: set = set()
        if enrollment_ids:
            async for pr in db.pause_requests.find({
                "enrollment_id": {"$in": enrollment_ids},
                "status": {"$in": ["active", "approved"]},
                "period": target_period,
            }):
                paused_enrollment_ids.add(pr.get("enrollment_id"))

        # Attendance rows for this date.
        attendance_by_student: dict = {}
        async for a in db.attendance.find({"session_id": session_id, "date": date_str}):
            attendance_by_student[a.get("student_id")] = a.get("status")

        roster = []
        for e in enrollments:
            sid = e["student_id"]
            stu = students_by_id.get(sid, {})
            first = stu.get("first_name", "")
            last = stu.get("last_name", "")
            name = f"{first} {last}".strip() or "Unknown"
            roster.append({
                "student_id": sid,
                "name": name,
                "has_medical_notes": bool((stu.get("medical_notes") or "").strip()),
                "is_paused": (
                    target_period in (e.get("skip_periods", []) or [])
                    or str(e["_id"]) in paused_enrollment_ids
                ),
                "attendance_status": attendance_by_student.get(sid),
            })

        sessions_out.append({
            "id": session_id,
            "name": s.get("name", ""),
            "start_time": s.get("start_time"),
            "end_time": s.get("end_time"),
            "roster": roster,
            "shortcuts": {
                "attendance_path": f"/coach/sessions/{session_id}",
                "lesson_plan_path": f"/coach/sessions/{session_id}",
                "progress_note_path": f"/coach/sessions/{session_id}",
            },
        })

    sessions_out.sort(key=lambda x: (x.get("start_time") or "", x["name"]))

    return {
        "date": date_str,
        "timezone": tz_name,
        "sessions": sessions_out,
    }
