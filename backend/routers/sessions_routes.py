"""Sessions + Enrollments + Students."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from models import SessionIn, EnrollmentIn, StudentIn, TransferIn
from auth import get_current_user, require_roles, log_audit
from db import get_db

router = APIRouter()


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


# ----------------- /api/sessions -----------------
@router.get("/sessions")
async def list_sessions(user=Depends(get_current_user)):
    db = get_db()
    q = {"is_deleted": {"$ne": True}}
    if user["role"] == "coach":
        q["coach_id"] = user["id"]
    cursor = db.sessions.find(q).sort("start_date", -1)
    items = await cursor.to_list(500)
    coach_ids = {it.get("coach_id") for it in items if it.get("coach_id")}
    coaches = {}
    if coach_ids:
        async for c in db.users.find({"_id": {"$in": [ObjectId(c) for c in coach_ids]}}):
            coaches[str(c["_id"])] = c.get("name", c.get("email"))
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["coach_name"] = coaches.get(it.get("coach_id"), "Unassigned")
    return items


@router.post("/sessions")
async def create_session(body: SessionIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    doc = body.model_dump()
    doc["is_deleted"] = False
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.sessions.insert_one(doc)
    await log_audit(admin, "create", "session", str(result.inserted_id), body.name)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("/sessions/{sid}")
async def get_session(sid: str, user=Depends(get_current_user)):
    db = get_db()
    s = await db.sessions.find_one({"_id": _oid(sid), "is_deleted": {"$ne": True}})
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    s["id"] = str(s.pop("_id"))
    if s.get("coach_id"):
        c = await db.users.find_one({"_id": ObjectId(s["coach_id"])})
        s["coach_name"] = c.get("name", c.get("email")) if c else "Unassigned"
    else:
        s["coach_name"] = "Unassigned"
    return s


@router.patch("/sessions/{sid}")
async def update_session(sid: str, body: SessionIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    update = body.model_dump()
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.sessions.update_one({"_id": _oid(sid)}, {"$set": update})
    await log_audit(admin, "update", "session", sid, body.name)
    return {"ok": True}


@router.delete("/sessions/{sid}")
async def delete_session(sid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    await db.sessions.update_one({"_id": _oid(sid)}, {"$set": {"is_deleted": True}})
    await log_audit(admin, "delete", "session", sid, "soft delete")
    return {"ok": True}


@router.post("/sessions/{sid}/cancel")
async def cancel_session(sid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    await db.sessions.update_one({"_id": _oid(sid)}, {"$set": {"status": "cancelled"}})
    await log_audit(admin, "cancel", "session", sid, "cancelled")
    return {"ok": True}


# ----------------- /api/students -----------------
def _age_from_dob(dob: str) -> int:
    try:
        d = datetime.fromisoformat(dob)
        today = datetime.now()
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    except Exception:
        return 0


@router.post("/students")
async def create_student(body: StudentIn, user=Depends(get_current_user)):
    if user["role"] not in ("admin", "parent"):
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    doc = body.model_dump()
    doc["parent_user_id"] = user["id"]
    doc["age"] = _age_from_dob(body.dob)
    doc["status"] = "active"
    doc["is_deleted"] = False
    doc["waiver_date"] = datetime.now(timezone.utc).isoformat() if body.waiver_accepted else None
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.students.insert_one(doc)
    await log_audit(user, "create", "student", str(result.inserted_id), f"{body.first_name} {body.last_name}")
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("/students")
async def list_students(session_id: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {"is_deleted": {"$ne": True}}
    if user["role"] == "parent":
        q["parent_user_id"] = user["id"]
    elif user["role"] == "coach":
        # Coach only sees students enrolled in their sessions
        sess = await db.sessions.find({"coach_id": user["id"], "is_deleted": {"$ne": True}}, {"_id": 1}).to_list(500)
        sids = [str(s["_id"]) for s in sess]
        if not sids:
            return []
        enrolls = await db.enrollments.find({"session_id": {"$in": sids}, "status": "active"}, {"student_id": 1}).to_list(2000)
        stu_ids = [ObjectId(e["student_id"]) for e in enrolls]
        q["_id"] = {"$in": stu_ids}
    if session_id and user["role"] in ("admin", "coach"):
        enrolls = await db.enrollments.find({"session_id": session_id, "status": "active"}, {"student_id": 1}).to_list(2000)
        stu_ids = [ObjectId(e["student_id"]) for e in enrolls]
        q["_id"] = {"$in": stu_ids}
    cursor = db.students.find(q).sort("created_at", -1)
    items = await cursor.to_list(2000)
    parent_ids = {it.get("parent_user_id") for it in items if it.get("parent_user_id")}
    parents = {}
    if parent_ids:
        async for p in db.users.find({"_id": {"$in": [ObjectId(p) for p in parent_ids]}}):
            parents[str(p["_id"])] = {"name": p.get("name"), "email": p.get("email"), "phone": p.get("phone")}
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["parent"] = parents.get(it.get("parent_user_id"), {})
    return items


@router.get("/students/{sid}")
async def get_student(sid: str, user=Depends(get_current_user)):
    db = get_db()
    s = await db.students.find_one({"_id": _oid(sid)})
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] == "parent" and s.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    s["id"] = str(s.pop("_id"))
    return s


@router.patch("/students/{sid}")
async def update_student(sid: str, body: StudentIn, user=Depends(get_current_user)):
    db = get_db()
    s = await db.students.find_one({"_id": _oid(sid)})
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] == "parent" and s.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    update = body.model_dump()
    update["age"] = _age_from_dob(body.dob)
    await db.students.update_one({"_id": _oid(sid)}, {"$set": update})
    await log_audit(user, "update", "student", sid, "")
    return {"ok": True}


@router.delete("/students/{sid}")
async def delete_student(sid: str, user=Depends(get_current_user)):
    db = get_db()
    s = await db.students.find_one({"_id": _oid(sid)})
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] not in ("admin",) and s.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.students.update_one({"_id": _oid(sid)}, {"$set": {"is_deleted": True}})
    await log_audit(user, "delete", "student", sid, "soft delete")
    return {"ok": True}


# ----------------- /api/enrollments -----------------
@router.post("/enrollments")
async def create_enrollment(body: EnrollmentIn, user=Depends(get_current_user)):
    db = get_db()
    if user["role"] not in ("admin", "parent"):
        raise HTTPException(status_code=403, detail="Forbidden")
    student = await db.students.find_one({"_id": _oid(body.student_id)})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] == "parent" and student.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Cannot enroll another parent's child")
    session = await db.sessions.find_one({"_id": _oid(body.session_id), "is_deleted": {"$ne": True}})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Capacity check
    active_count = await db.enrollments.count_documents({"session_id": body.session_id, "status": "active"})
    if active_count >= int(session.get("max_students", 999)):
        raise HTTPException(status_code=400, detail="Session is full")
    existing = await db.enrollments.find_one({"session_id": body.session_id, "student_id": body.student_id})
    if existing and existing.get("status") == "active":
        raise HTTPException(status_code=400, detail="Already enrolled")
    doc = {
        "session_id": body.session_id,
        "student_id": body.student_id,
        "parent_user_id": student.get("parent_user_id"),
        "billing_type": body.billing_type or "Standard",
        "approval_status": "approved" if user["role"] == "admin" else "pending",
        "status": "active",
        "enrolled_at": datetime.now(timezone.utc).isoformat(),
        "is_deleted": False,
    }
    if existing:
        await db.enrollments.update_one({"_id": existing["_id"]}, {"$set": doc})
        eid = str(existing["_id"])
    else:
        r = await db.enrollments.insert_one(doc)
        eid = str(r.inserted_id)
    await log_audit(user, "create", "enrollment", eid, f"student {body.student_id} -> session {body.session_id}")
    doc.pop("_id", None)
    return {"id": eid, **doc}


@router.get("/enrollments")
async def list_enrollments(session_id: str | None = None, student_id: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {"is_deleted": {"$ne": True}}
    if session_id:
        q["session_id"] = session_id
    if student_id:
        q["student_id"] = student_id
    if user["role"] == "parent":
        q["parent_user_id"] = user["id"]
    elif user["role"] == "coach":
        sess = await db.sessions.find({"coach_id": user["id"]}, {"_id": 1}).to_list(500)
        sids = [str(s["_id"]) for s in sess]
        q["session_id"] = {"$in": sids} if not session_id else session_id
    cursor = db.enrollments.find(q).sort("enrolled_at", -1)
    items = await cursor.to_list(2000)
    stu_ids = {it["student_id"] for it in items}
    students = {}
    if stu_ids:
        async for s in db.students.find({"_id": {"$in": [ObjectId(x) for x in stu_ids]}}):
            students[str(s["_id"])] = {"first_name": s["first_name"], "last_name": s["last_name"], "age": s.get("age")}
    sess_ids = {it["session_id"] for it in items}
    sessions = {}
    if sess_ids:
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in sess_ids]}}):
            sessions[str(s["_id"])] = {"name": s["name"], "monthly_price": s.get("monthly_price")}
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["student"] = students.get(it["student_id"], {})
        it["session"] = sessions.get(it["session_id"], {})
    return items


@router.post("/enrollments/{eid}/cancel")
async def cancel_enrollment(eid: str, user=Depends(get_current_user)):
    db = get_db()
    e = await db.enrollments.find_one({"_id": _oid(eid)})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] == "parent" and e.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.enrollments.update_one({"_id": _oid(eid)}, {"$set": {"status": "cancelled"}})
    await log_audit(user, "cancel", "enrollment", eid, "")
    return {"ok": True}


@router.post("/enrollments/{eid}/approve")
async def approve_enrollment(eid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    e = await db.enrollments.find_one({"_id": _oid(eid)})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    await db.enrollments.update_one(
        {"_id": _oid(eid)},
        {"$set": {"approval_status": "approved", "approved_by": admin["id"],
                  "approved_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_audit(admin, "approve", "enrollment", eid, "")
    return {"ok": True}


@router.post("/enrollments/{eid}/transfer")
async def transfer_enrollment(eid: str, body: "TransferIn", admin=Depends(require_roles("admin"))):
    db = get_db()
    e = await db.enrollments.find_one({"_id": _oid(eid)})
    if not e:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    to_session = await db.sessions.find_one({"_id": _oid(body.to_session_id), "is_deleted": {"$ne": True}})
    if not to_session:
        raise HTTPException(status_code=404, detail="Target session not found")
    from_session_id = e["session_id"]
    move_doc = {
        "enrollment_id": eid,
        "student_id": e["student_id"],
        "from_session_id": from_session_id,
        "to_session_id": body.to_session_id,
        "effective_month": body.effective_month,
        "permanent": bool(body.permanent),
        "note": body.note or "",
        "moved_by": admin["id"],
        "moved_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.move_log.insert_one(move_doc)
    if body.permanent:
        # Capacity check on target
        active_count = await db.enrollments.count_documents({"session_id": body.to_session_id, "status": "active"})
        if active_count >= int(to_session.get("max_students", 999)):
            raise HTTPException(status_code=400, detail="Target session is full")
        await db.enrollments.update_one(
            {"_id": _oid(eid)},
            {"$set": {"session_id": body.to_session_id}},
        )
    else:
        # Single-month override
        overrides = e.get("session_overrides", {}) or {}
        overrides[body.effective_month] = body.to_session_id
        await db.enrollments.update_one(
            {"_id": _oid(eid)},
            {"$set": {"session_overrides": overrides}},
        )
    await log_audit(admin, "transfer", "enrollment", eid,
                    f"{'permanent' if body.permanent else 'override-' + body.effective_month}")
    return {"ok": True}


@router.get("/move-log")
async def list_move_log(user=Depends(get_current_user)):
    if user["role"] not in ("admin", "coach"):
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    cursor = db.move_log.find().sort("moved_at", -1).limit(500)
    items = await cursor.to_list(500)
    stu_ids = {it["student_id"] for it in items}
    sess_ids = {it["from_session_id"] for it in items} | {it["to_session_id"] for it in items}
    students = {}
    sessions = {}
    if stu_ids:
        async for s in db.students.find({"_id": {"$in": [ObjectId(x) for x in stu_ids]}}):
            students[str(s["_id"])] = f"{s['first_name']} {s['last_name']}"
    if sess_ids:
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in sess_ids]}}):
            sessions[str(s["_id"])] = s["name"]
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["student_name"] = students.get(it["student_id"], "")
        it["from_session_name"] = sessions.get(it["from_session_id"], "")
        it["to_session_name"] = sessions.get(it["to_session_id"], "")
    return items
