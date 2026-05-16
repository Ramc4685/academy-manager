"""Sessions + Enrollments + Students."""
import asyncio
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from models import (
    SessionIn, EnrollmentIn, StudentIn, TransferIn,
    PauseRequestIn, PauseRequestDecisionIn,
)
from auth import get_current_user, require_roles, log_audit
from db import get_db
from services.enrollment_service import (
    APPROVED_ENROLLMENT_APPROVAL_STATUS,
    capacity_snapshot,
    create_enrollment_with_capacity,
    initialize_reserved_seats,
    release_session_seat,
    reserve_session_seat,
)
from services.waitlist_service import join_waitlist, promote_next_waitlist
from services.waiver_service import record_waiver_acceptance, waiver_fields

router = APIRouter()


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


def _valid_period(period: str) -> bool:
    try:
        datetime.strptime(period, "%Y-%m")
        return True
    except Exception:
        return False


def _resume_timestamp_after_period(period: str) -> int:
    year, month = [int(x) for x in period.split("-")]
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())


async def _stripe_pause_collection(subscription_id: str, period: str) -> str:
    """Pause Stripe collection when the paused month has started.
    Future month pauses stay scheduled in the app until a scheduler applies them."""
    if not subscription_id:
        return "not_applicable"
    if period > datetime.now(timezone.utc).strftime("%Y-%m"):
        return "scheduled_in_app"
    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        return "stripe_not_configured"
    try:
        import stripe
        stripe.api_key = api_key
        await asyncio.to_thread(
            stripe.Subscription.modify,
            subscription_id,
            pause_collection={"behavior": "void", "resumes_at": _resume_timestamp_after_period(period)},
        )
        return "stripe_paused"
    except Exception:
        return "stripe_pause_failed"


async def _stripe_resume_collection(subscription_id: str) -> str:
    if not subscription_id or not os.environ.get("STRIPE_API_KEY"):
        return "not_applicable"
    try:
        import stripe
        stripe.api_key = os.environ["STRIPE_API_KEY"]
        await asyncio.to_thread(stripe.Subscription.modify, subscription_id, pause_collection="")
        return "stripe_resumed"
    except Exception:
        return "stripe_resume_failed"


async def _coach_session_ids(db, coach_id: str) -> list[str]:
    sessions = await db.sessions.find(
        {"coach_id": coach_id, "is_deleted": {"$ne": True}},
        {"_id": 1},
    ).to_list(500)
    return [str(s["_id"]) for s in sessions]


async def _coach_can_access_student(db, coach_id: str, student_id: str) -> bool:
    session_ids = await _coach_session_ids(db, coach_id)
    if not session_ids:
        return False
    enrollment = await db.enrollments.find_one({
        "session_id": {"$in": session_ids},
        "student_id": student_id,
        "status": "active",
        "approval_status": APPROVED_ENROLLMENT_APPROVAL_STATUS,
        "is_deleted": {"$ne": True},
    })
    return enrollment is not None


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
        it.update(await capacity_snapshot(db, it))
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
    if user["role"] == "coach" and s.get("coach_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    s.update(await capacity_snapshot(db, s))
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
    if body.waiver_accepted:
        doc.update(waiver_fields(user["id"]))
    else:
        doc["waiver_date"] = None
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.students.insert_one(doc)
    if body.waiver_accepted:
        await record_waiver_acceptance(
            db,
            student_id=str(result.inserted_id),
            parent_user_id=doc.get("parent_user_id"),
            accepted_by_user_id=user["id"],
        )
    await log_audit(user, "create", "student", str(result.inserted_id), f"{body.first_name} {body.last_name}")
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("/students")
async def list_students(session_id: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {"is_deleted": {"$ne": True}}
    coach_session_ids = None
    if user["role"] == "parent":
        q["parent_user_id"] = user["id"]
    elif user["role"] == "coach":
        # Coach only sees students enrolled in their sessions
        sids = await _coach_session_ids(db, user["id"])
        coach_session_ids = sids
        if not sids:
            return []
        if session_id and session_id not in sids:
            raise HTTPException(status_code=403, detail="Forbidden")
        enrollment_query = {"session_id": session_id or {"$in": sids}, "status": "active"}
        enrollment_query["is_deleted"] = {"$ne": True}
        enrollment_query["approval_status"] = APPROVED_ENROLLMENT_APPROVAL_STATUS
        enrolls = await db.enrollments.find(enrollment_query, {"student_id": 1}).to_list(2000)
        stu_ids = [ObjectId(e["student_id"]) for e in enrolls]
        q["_id"] = {"$in": stu_ids}
    elif session_id and user["role"] == "admin":
        enrolls = await db.enrollments.find(
            {"session_id": session_id, "status": "active", "is_deleted": {"$ne": True}},
            {"student_id": 1},
        ).to_list(2000)
        stu_ids = [ObjectId(e["student_id"]) for e in enrolls]
        q["_id"] = {"$in": stu_ids}
    cursor = db.students.find(q).sort("created_at", -1)
    items = await cursor.to_list(2000)
    parent_ids = {it.get("parent_user_id") for it in items if it.get("parent_user_id")}
    parents = {}
    if parent_ids:
        async for p in db.users.find({"_id": {"$in": [ObjectId(p) for p in parent_ids]}}):
            parents[str(p["_id"])] = {"name": p.get("name"), "email": p.get("email"), "phone": p.get("phone")}
    # Enrollments per student
    student_ids_str = [str(it["_id"]) for it in items]
    enrollments_query = {
        "student_id": {"$in": student_ids_str},
        "status": "active", "is_deleted": {"$ne": True},
    }
    if user["role"] == "coach":
        enrollments_query["session_id"] = {"$in": coach_session_ids or []}
        enrollments_query["approval_status"] = APPROVED_ENROLLMENT_APPROVAL_STATUS
    enrolls = await db.enrollments.find(enrollments_query).to_list(5000)
    sess_ids = {e["session_id"] for e in enrolls}
    sessions = {}
    if sess_ids:
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in sess_ids]}}):
            sessions[str(s["_id"])] = {"id": str(s["_id"]), "name": s["name"], "monthly_price": s.get("monthly_price")}
    by_student: dict = {}
    for e in enrolls:
        sess = sessions.get(e["session_id"])
        if not sess:
            continue
        by_student.setdefault(e["student_id"], []).append({
            "enrollment_id": str(e["_id"]),
            "session_id": e["session_id"],
            "session_name": sess["name"],
            "billing_type": e.get("billing_type", "Standard"),
            "approval_status": e.get("approval_status", "approved"),
            "skip_periods": e.get("skip_periods", []),
            "payment_mode": e.get("payment_mode", "manual"),
            "subscription_status": e.get("subscription_status"),
        })
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["parent"] = parents.get(it.get("parent_user_id"), {})
        it["enrollments"] = by_student.get(it["id"], [])
    return items


@router.get("/students/{sid}")
async def get_student(sid: str, user=Depends(get_current_user)):
    db = get_db()
    s = await db.students.find_one({"_id": _oid(sid)})
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] == "parent" and s.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "coach" and not await _coach_can_access_student(db, user["id"], sid):
        raise HTTPException(status_code=403, detail="Forbidden")
    s["id"] = str(s.pop("_id"))
    return s


@router.patch("/students/{sid}")
async def update_student(sid: str, body: StudentIn, user=Depends(get_current_user)):
    db = get_db()
    s = await db.students.find_one({"_id": _oid(sid)})
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] not in ("admin", "parent"):
        raise HTTPException(status_code=403, detail="Forbidden")
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
    try:
        eid, doc = await create_enrollment_with_capacity(
            db,
            session_id=body.session_id,
            student=student,
            actor_role=user["role"],
            billing_type=body.billing_type or "Standard",
        )
    except HTTPException as exc:
        if user["role"] == "parent" and exc.status_code == 400 and exc.detail == "Session is full":
            wid, waitlist_doc = await join_waitlist(
                db,
                session_id=body.session_id,
                student=student,
                requested_by=user["id"],
            )
            await log_audit(user, "join", "waitlist", wid, f"student {body.student_id} -> session {body.session_id}")
            waitlist_doc.pop("_id", None)
            return {"waitlisted": True, "waitlist_id": wid, **waitlist_doc}
        raise
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
        sids = await _coach_session_ids(db, user["id"])
        if session_id and session_id not in sids:
            raise HTTPException(status_code=403, detail="Forbidden")
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
    if e.get("status") == "active":
        await initialize_reserved_seats(db, e["session_id"])
        result = await db.enrollments.update_one(
            {"_id": _oid(eid), "session_id": e["session_id"], "status": "active"},
            {"$set": {"status": "cancelled"}},
        )
        if result.modified_count:
            await release_session_seat(db, e["session_id"])
            await promote_next_waitlist(db, e["session_id"])
    else:
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
    if body.permanent:
        if body.to_session_id != from_session_id:
            if e.get("status") != "active":
                raise HTTPException(status_code=400, detail="Only active enrollments can be transferred")
            if e.get("status") == "active":
                await initialize_reserved_seats(db, from_session_id)
            await reserve_session_seat(db, body.to_session_id)
            try:
                result = await db.enrollments.update_one(
                    {"_id": _oid(eid), "session_id": from_session_id, "status": "active"},
                    {"$set": {"session_id": body.to_session_id}},
                )
            except Exception:
                await release_session_seat(db, body.to_session_id)
                raise
            if result.modified_count != 1:
                await release_session_seat(db, body.to_session_id)
                raise HTTPException(status_code=409, detail="Enrollment changed; retry transfer")
            await release_session_seat(db, from_session_id)
    else:
        # Single-month override
        overrides = e.get("session_overrides", {}) or {}
        overrides[body.effective_month] = body.to_session_id
        await db.enrollments.update_one(
            {"_id": _oid(eid)},
            {"$set": {"session_overrides": overrides}},
        )
    await db.move_log.insert_one(move_doc)
    await log_audit(admin, "transfer", "enrollment", eid,
                    f"{'permanent' if body.permanent else 'override-' + body.effective_month}")
    return {"ok": True}


@router.post("/enrollments/{eid}/pause-month")
async def pause_month(eid: str, period: str, admin=Depends(require_roles("admin"))):
    """Mark an enrollment as paused for a specific YYYY-MM period.
    Payment generation will skip this month; dashboards exclude paused months."""
    db = get_db()
    if not _valid_period(period):
        raise HTTPException(status_code=400, detail="Invalid period")
    e = await db.enrollments.find_one({"_id": _oid(eid)})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    skip = list(e.get("skip_periods", []) or [])
    if period not in skip:
        skip.append(period)
    stripe_pause_status = await _stripe_pause_collection(e.get("stripe_subscription_id"), period)
    await db.enrollments.update_one(
        {"_id": _oid(eid)},
        {"$set": {
            "skip_periods": skip,
            "stripe_pause_status": stripe_pause_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    await log_audit(admin, "pause_month", "enrollment", eid, period)
    return {"ok": True, "skip_periods": skip, "stripe_pause_status": stripe_pause_status}


@router.post("/enrollments/{eid}/resume-month")
async def resume_month(eid: str, period: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    if not _valid_period(period):
        raise HTTPException(status_code=400, detail="Invalid period")
    e = await db.enrollments.find_one({"_id": _oid(eid)})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    skip = [p for p in (e.get("skip_periods", []) or []) if p != period]
    stripe_resume_status = "not_applicable"
    if period <= datetime.now(timezone.utc).strftime("%Y-%m"):
        stripe_resume_status = await _stripe_resume_collection(e.get("stripe_subscription_id"))
    await db.enrollments.update_one(
        {"_id": _oid(eid)},
        {"$set": {
            "skip_periods": skip,
            "stripe_pause_status": stripe_resume_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    await log_audit(admin, "resume_month", "enrollment", eid, period)
    return {"ok": True, "skip_periods": skip, "stripe_resume_status": stripe_resume_status}


async def _enrich_pause_request(db, item: dict) -> dict:
    item["id"] = str(item.pop("_id"))
    student = await db.students.find_one({"_id": ObjectId(item["student_id"])}) if item.get("student_id") else None
    session = await db.sessions.find_one({"_id": ObjectId(item["session_id"])}) if item.get("session_id") else None
    parent = await db.users.find_one({"_id": ObjectId(item["parent_user_id"])}) if item.get("parent_user_id") else None
    item["student_name"] = f"{student['first_name']} {student['last_name']}" if student else ""
    item["session_name"] = session.get("name", "") if session else ""
    item["parent_name"] = parent.get("name", "") if parent else ""
    item["parent_email"] = parent.get("email", "") if parent else ""
    return item


@router.get("/pause-requests")
async def list_pause_requests(status: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    if user["role"] not in {"admin", "parent"}:
        raise HTTPException(status_code=403, detail="Forbidden")
    q: dict = {}
    if status:
        q["status"] = status
    if user["role"] == "parent":
        q["parent_user_id"] = user["id"]
    cursor = db.pause_requests.find(q).sort("created_at", -1)
    items = await cursor.to_list(1000)
    return [await _enrich_pause_request(db, it) for it in items]


@router.post("/pause-requests")
async def create_pause_request(body: PauseRequestIn, user=Depends(get_current_user)):
    if user["role"] != "parent":
        raise HTTPException(status_code=403, detail="Only parents can request a pause")
    if not _valid_period(body.period):
        raise HTTPException(status_code=400, detail="Invalid period")
    db = get_db()
    enrollment = await db.enrollments.find_one({"_id": _oid(body.enrollment_id), "is_deleted": {"$ne": True}})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if enrollment.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Not your enrollment")
    if enrollment.get("status") != "active":
        raise HTTPException(status_code=400, detail="Only active enrollments can be paused")
    if body.period in (enrollment.get("skip_periods", []) or []):
        raise HTTPException(status_code=400, detail="Enrollment is already paused for this month")
    existing = await db.pause_requests.find_one({
        "enrollment_id": body.enrollment_id,
        "period": body.period,
        "status": {"$in": ["pending", "approved"]},
    })
    if existing:
        raise HTTPException(status_code=400, detail="Pause request already exists for this month")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "enrollment_id": body.enrollment_id,
        "parent_user_id": enrollment["parent_user_id"],
        "student_id": enrollment["student_id"],
        "session_id": enrollment["session_id"],
        "period": body.period,
        "reason": body.reason or "",
        "status": "pending",
        "payment_mode": enrollment.get("payment_mode", "manual"),
        "subscription_status": enrollment.get("subscription_status"),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.pause_requests.insert_one(doc)
    await db.notifications.insert_one({
        "user_id": enrollment["parent_user_id"],
        "type": "pause_requested",
        "title": "Pause request submitted",
        "message": f"Pause requested for {body.period}. Admin approval is required.",
        "related_entity": str(result.inserted_id),
        "read": False,
        "created_at": now,
    })
    await log_audit(user, "request_pause", "enrollment", body.enrollment_id, body.period)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.post("/pause-requests/{rid}/approve")
async def approve_pause_request(rid: str, body: PauseRequestDecisionIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    req = await db.pause_requests.find_one({"_id": _oid(rid)})
    if not req:
        raise HTTPException(status_code=404, detail="Pause request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Only pending pause requests can be approved")
    enrollment = await db.enrollments.find_one({"_id": _oid(req["enrollment_id"])})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    skip = list(enrollment.get("skip_periods", []) or [])
    if req["period"] not in skip:
        skip.append(req["period"])
    stripe_pause_status = await _stripe_pause_collection(enrollment.get("stripe_subscription_id"), req["period"])
    now = datetime.now(timezone.utc).isoformat()
    await db.enrollments.update_one(
        {"_id": enrollment["_id"]},
        {"$set": {
            "skip_periods": skip,
            "stripe_pause_status": stripe_pause_status,
            "updated_at": now,
        }},
    )
    await db.pause_requests.update_one(
        {"_id": _oid(rid)},
        {"$set": {
            "status": "approved",
            "decision_note": body.note or "",
            "decided_by": admin["id"],
            "decided_at": now,
            "stripe_pause_status": stripe_pause_status,
            "updated_at": now,
        }},
    )
    await db.notifications.insert_one({
        "user_id": req["parent_user_id"],
        "type": "pause_approved",
        "title": "Pause request approved",
        "message": f"Your pause request for {req['period']} was approved.",
        "related_entity": rid,
        "read": False,
        "created_at": now,
    })
    await log_audit(admin, "approve_pause_request", "pause_request", rid, req["period"])
    return {"ok": True, "skip_periods": skip, "stripe_pause_status": stripe_pause_status}


@router.post("/pause-requests/{rid}/decline")
async def decline_pause_request(rid: str, body: PauseRequestDecisionIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    req = await db.pause_requests.find_one({"_id": _oid(rid)})
    if not req:
        raise HTTPException(status_code=404, detail="Pause request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Only pending pause requests can be declined")
    now = datetime.now(timezone.utc).isoformat()
    await db.pause_requests.update_one(
        {"_id": _oid(rid)},
        {"$set": {
            "status": "declined",
            "decision_note": body.note or "",
            "decided_by": admin["id"],
            "decided_at": now,
            "updated_at": now,
        }},
    )
    await db.notifications.insert_one({
        "user_id": req["parent_user_id"],
        "type": "pause_declined",
        "title": "Pause request declined",
        "message": f"Your pause request for {req['period']} was declined.",
        "related_entity": rid,
        "read": False,
        "created_at": now,
    })
    await log_audit(admin, "decline_pause_request", "pause_request", rid, req["period"])
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
