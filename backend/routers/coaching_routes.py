"""Attendance + Lesson Plans + Progress Notes."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from models import AttendanceBulkIn, LessonPlanIn, ProgressNoteIn
from auth import get_current_user, require_roles, log_audit
from db import get_db
from services.enrollment_service import APPROVED_ENROLLMENT_APPROVAL_STATUS

router = APIRouter()


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


async def _coach_owns_session(user, session_id: str) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] != "coach":
        return False
    db = get_db()
    s = await db.sessions.find_one({"_id": _oid(session_id), "is_deleted": {"$ne": True}})
    return s and s.get("coach_id") == user["id"]


async def _coach_session_ids(db, coach_id: str) -> list[str]:
    sessions = await db.sessions.find(
        {"coach_id": coach_id, "is_deleted": {"$ne": True}},
        {"_id": 1},
    ).to_list(500)
    return [str(s["_id"]) for s in sessions]


async def _parent_student_ids(db, parent_id: str) -> list[str]:
    students = await db.students.find(
        {"parent_user_id": parent_id, "is_deleted": {"$ne": True}},
        {"_id": 1},
    ).to_list(500)
    return [str(s["_id"]) for s in students]


async def _coach_can_access_student(db, coach_id: str, student_id: str, session_id: str | None = None) -> bool:
    session_ids = await _coach_session_ids(db, coach_id)
    if not session_ids:
        return False
    if session_id:
        if session_id not in session_ids:
            return False
        session_filter = session_id
    else:
        session_filter = {"$in": session_ids}
    enrollment = await db.enrollments.find_one({
        "session_id": session_filter,
        "student_id": student_id,
        "status": "active",
        "approval_status": APPROVED_ENROLLMENT_APPROVAL_STATUS,
        "is_deleted": {"$ne": True},
    })
    return enrollment is not None


# ----------------- /api/attendance -----------------
@router.post("/attendance/bulk")
async def bulk_attendance(body: AttendanceBulkIn, user=Depends(get_current_user)):
    db = get_db()
    if not await _coach_owns_session(user, body.session_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    upserts = 0
    for item in body.items:
        # find enrollment
        enr = await db.enrollments.find_one({"session_id": body.session_id, "student_id": item.student_id})
        doc = {
            "session_id": body.session_id,
            "student_id": item.student_id,
            "enrollment_id": str(enr["_id"]) if enr else None,
            "date": body.date,
            "status": item.status,
            "notes": item.notes or "",
            "marked_by": user["id"],
            "marked_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.attendance.update_one(
            {"session_id": body.session_id, "student_id": item.student_id, "date": body.date},
            {"$set": doc},
            upsert=True,
        )
        upserts += 1
    await log_audit(user, "mark_attendance", "attendance", body.session_id, f"{body.date} count={upserts}")
    return {"updated": upserts}


@router.get("/attendance")
async def list_attendance(session_id: str | None = None, student_id: str | None = None,
                          date: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {}
    if session_id:
        q["session_id"] = session_id
    if student_id:
        q["student_id"] = student_id
    if date:
        q["date"] = date
    if user["role"] == "parent":
        # Only own children
        sids = await _parent_student_ids(db, user["id"])
        if not sids:
            return []
        if student_id and student_id not in sids:
            raise HTTPException(status_code=403, detail="Forbidden")
        q["student_id"] = {"$in": sids} if not student_id else student_id
    elif user["role"] == "coach":
        ids = await _coach_session_ids(db, user["id"])
        if session_id and session_id not in ids:
            raise HTTPException(status_code=403, detail="Forbidden")
        if student_id and not await _coach_can_access_student(db, user["id"], student_id, session_id):
            raise HTTPException(status_code=403, detail="Forbidden")
        q["session_id"] = {"$in": ids} if not session_id else session_id
    cursor = db.attendance.find(q).sort("date", -1)
    items = await cursor.to_list(2000)
    stu_ids = {it["student_id"] for it in items}
    students = {}
    if stu_ids:
        async for s in db.students.find({"_id": {"$in": [ObjectId(x) for x in stu_ids]}}):
            students[str(s["_id"])] = f"{s['first_name']} {s['last_name']}"
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["student_name"] = students.get(it["student_id"], "")
    return items


# ----------------- /api/lesson-plans -----------------
@router.get("/lesson-plans")
async def list_lesson_plans(session_id: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {}
    if session_id:
        q["session_id"] = session_id
    if user["role"] == "coach":
        if session_id and not await _coach_owns_session(user, session_id):
            raise HTTPException(status_code=403, detail="Forbidden")
        q["coach_id"] = user["id"]
    elif user["role"] == "parent":
        # only sessions for own students
        sids = await _parent_student_ids(db, user["id"])
        enrolls = await db.enrollments.find({
            "student_id": {"$in": sids},
            "status": "active",
            "approval_status": APPROVED_ENROLLMENT_APPROVAL_STATUS,
        }, {"session_id": 1}).to_list(500)
        sess_ids = list({e["session_id"] for e in enrolls})
        if session_id and session_id not in sess_ids:
            raise HTTPException(status_code=403, detail="Forbidden")
        q["session_id"] = {"$in": sess_ids} if not session_id else session_id
    cursor = db.lesson_plans.find(q).sort("date", -1)
    items = await cursor.to_list(500)
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


@router.post("/lesson-plans")
async def create_lesson_plan(body: LessonPlanIn, user=Depends(get_current_user)):
    if not await _coach_owns_session(user, body.session_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    doc = body.model_dump()
    doc["coach_id"] = user["id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    r = await db.lesson_plans.insert_one(doc)
    await log_audit(user, "create", "lesson_plan", str(r.inserted_id), body.objective[:50])
    doc.pop("_id", None)
    return {"id": str(r.inserted_id), **doc}


@router.patch("/lesson-plans/{lid}")
async def update_lesson_plan(lid: str, body: LessonPlanIn, user=Depends(get_current_user)):
    db = get_db()
    lp = await db.lesson_plans.find_one({"_id": _oid(lid)})
    if not lp:
        raise HTTPException(status_code=404, detail="Lesson plan not found")
    if user["role"] != "admin" and lp.get("coach_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.lesson_plans.update_one({"_id": _oid(lid)}, {"$set": body.model_dump()})
    return {"ok": True}


@router.delete("/lesson-plans/{lid}")
async def delete_lesson_plan(lid: str, user=Depends(get_current_user)):
    db = get_db()
    lp = await db.lesson_plans.find_one({"_id": _oid(lid)})
    if not lp:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] != "admin" and lp.get("coach_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.lesson_plans.delete_one({"_id": _oid(lid)})
    return {"ok": True}


# ----------------- /api/progress-notes -----------------
@router.get("/progress-notes")
async def list_progress_notes(student_id: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {}
    if student_id:
        q["student_id"] = student_id
    if user["role"] == "coach":
        # See notes only for students in coach's sessions
        sids = await _coach_session_ids(db, user["id"])
        enrolls = await db.enrollments.find({
            "session_id": {"$in": sids},
            "status": "active",
            "approval_status": APPROVED_ENROLLMENT_APPROVAL_STATUS,
        }, {"student_id": 1}).to_list(2000)
        stu_ids = list({e["student_id"] for e in enrolls})
        if student_id and student_id not in stu_ids:
            raise HTTPException(status_code=403, detail="Forbidden")
        q["student_id"] = {"$in": stu_ids} if not student_id else student_id
    elif user["role"] == "parent":
        sids = await _parent_student_ids(db, user["id"])
        if student_id and student_id not in sids:
            raise HTTPException(status_code=403, detail="Forbidden")
        q["student_id"] = {"$in": sids} if not student_id else student_id
    cursor = db.progress_notes.find(q).sort("created_at", -1)
    items = await cursor.to_list(500)
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


@router.post("/progress-notes")
async def create_progress_note(body: ProgressNoteIn, user=Depends(require_roles("coach", "admin"))):
    db = get_db()
    if user["role"] == "coach":
        if not await _coach_can_access_student(db, user["id"], body.student_id, body.session_id):
            raise HTTPException(status_code=403, detail="Forbidden")
    doc = body.model_dump()
    doc["coach_id"] = user["id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    r = await db.progress_notes.insert_one(doc)
    await log_audit(user, "create", "progress_note", str(r.inserted_id), body.note[:50])
    doc.pop("_id", None)
    return {"id": str(r.inserted_id), **doc}


@router.delete("/progress-notes/{nid}")
async def delete_progress_note(nid: str, user=Depends(require_roles("coach", "admin"))):
    db = get_db()
    n = await db.progress_notes.find_one({"_id": _oid(nid)})
    if not n:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] != "admin" and n.get("coach_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.progress_notes.delete_one({"_id": _oid(nid)})
    return {"ok": True}
