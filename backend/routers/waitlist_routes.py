"""Waitlist routes."""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.responses import Response, JSONResponse

from auth import get_current_user, require_roles, log_audit
from db import get_db
from models import EnrollmentIn
from services.enrollment_service import capacity_snapshot, initialize_reserved_seats
from services.waitlist_service import enroll_waitlist_offer, join_waitlist

router = APIRouter()


class _SkipBody(BaseModel):
    skipped_reason: Optional[str] = None


class _RemoveBody(BaseModel):
    removed_reason: Optional[str] = None


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


async def _enrich_waitlist(items: list[dict], db) -> list[dict]:
    student_ids = {it.get("student_id") for it in items if it.get("student_id")}
    session_ids = {it.get("session_id") for it in items if it.get("session_id")}
    parent_ids = {it.get("parent_user_id") for it in items if it.get("parent_user_id")}
    students = {}
    sessions = {}
    parents = {}
    if student_ids:
        async for s in db.students.find({"_id": {"$in": [ObjectId(x) for x in student_ids]}}):
            students[str(s["_id"])] = f"{s.get('first_name', '')} {s.get('last_name', '')}".strip()
    if session_ids:
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in session_ids]}}):
            sessions[str(s["_id"])] = s.get("name", "")
    if parent_ids:
        async for p in db.users.find({"_id": {"$in": [ObjectId(x) for x in parent_ids]}}, {"password_hash": 0}):
            parents[str(p["_id"])] = {"name": p.get("name"), "email": p.get("email"), "phone": p.get("phone", "")}
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["student_name"] = students.get(it.get("student_id"), "")
        it["session_name"] = sessions.get(it.get("session_id"), "")
        it["parent"] = parents.get(it.get("parent_user_id"), {})
    return items


@router.get("/waitlist")
async def list_waitlist(status: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {"is_deleted": {"$ne": True}}
    if status:
        q["status"] = status
    if user["role"] == "parent":
        q["parent_user_id"] = user["id"]
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    items = await db.waitlist.find(q).sort("requested_at", 1).to_list(1000)
    return await _enrich_waitlist(items, db)


@router.post("/waitlist")
async def create_waitlist_entry(body: EnrollmentIn, user=Depends(get_current_user)):
    if user["role"] not in ("admin", "parent"):
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    student = await db.students.find_one({"_id": _oid(body.student_id), "is_deleted": {"$ne": True}})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] == "parent" and student.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Cannot waitlist another parent's child")
    waitlist_id, doc = await join_waitlist(
        db,
        session_id=body.session_id,
        student=student,
        requested_by=user["id"],
    )
    await log_audit(user, "join", "waitlist", waitlist_id, f"student {body.student_id} -> session {body.session_id}")
    doc.pop("_id", None)
    return {"id": waitlist_id, **doc}


# ---------------------------------------------------------------------------
# Admin-only endpoints: /admin/waitlist/...
# ---------------------------------------------------------------------------


@router.get("/admin/waitlist")
async def admin_list_waitlist(session_id: str, admin=Depends(require_roles("admin"))):
    """Return FIFO-ordered waitlist entries for a session with next_candidate flag."""
    db = get_db()
    session = await db.sessions.find_one({"_id": _oid(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await initialize_reserved_seats(db, session_id)
    session = await db.sessions.find_one({"_id": _oid(session_id)})
    snapshot = await capacity_snapshot(db, session)
    has_free_seat = not snapshot["is_full"]

    # Fetch all non-deleted waitlist entries for this session, FIFO order
    raw_items = await db.waitlist.find(
        {"session_id": session_id, "is_deleted": {"$ne": True}}
    ).sort("requested_at", 1).to_list(1000)

    # Enrich with student and parent info
    student_ids = {it.get("student_id") for it in raw_items if it.get("student_id")}
    parent_ids = {it.get("parent_user_id") for it in raw_items if it.get("parent_user_id")}

    students: dict[str, str] = {}
    parents: dict[str, dict] = {}

    if student_ids:
        valid_sids = []
        for sid in student_ids:
            try:
                valid_sids.append(ObjectId(sid))
            except Exception:
                pass
        if valid_sids:
            async for s in db.students.find({"_id": {"$in": valid_sids}}):
                name = f"{s.get('first_name', '')} {s.get('last_name', '')}".strip()
                students[str(s["_id"])] = name or None

    if parent_ids:
        valid_pids = []
        for pid in parent_ids:
            try:
                valid_pids.append(ObjectId(pid))
            except Exception:
                pass
        if valid_pids:
            async for p in db.users.find({"_id": {"$in": valid_pids}}, {"password_hash": 0}):
                parents[str(p["_id"])] = {"email": p.get("email"), "name": p.get("name")}

    # Compute position and next_candidate: only the first "waiting" entry can be next_candidate
    first_waiting_found = False
    result = []
    for idx, item in enumerate(raw_items):
        entry_id = str(item["_id"])
        student_id_str = item.get("student_id", "")
        parent_id_str = item.get("parent_user_id", "")
        parent_info = parents.get(parent_id_str, {})

        is_next = False
        if item.get("status") == "waiting" and has_free_seat and not first_waiting_found:
            is_next = True
            first_waiting_found = True

        result.append({
            "id": entry_id,
            "parent_user_id": parent_id_str,
            "parent_email": parent_info.get("email"),
            "student_id": student_id_str,
            "student_name": students.get(student_id_str),
            "status": item.get("status"),
            "requested_at": item.get("requested_at"),
            "position": idx + 1,
            "next_candidate": is_next,
        })

    return result


@router.post("/admin/waitlist/{waitlist_id}/enroll")
async def admin_enroll_waitlist(waitlist_id: str, admin=Depends(require_roles("admin"))):
    """Atomically reserve a seat and enroll the waitlist candidate."""
    db = get_db()
    entry = await db.waitlist.find_one({"_id": _oid(waitlist_id), "is_deleted": {"$ne": True}})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    if entry.get("status") != "waiting":
        raise HTTPException(status_code=400, detail="Waitlist entry is not in waiting status")

    session_id = entry["session_id"]

    await initialize_reserved_seats(db, session_id)

    # Atomic capacity check + increment — same $expr pattern as Slice 3
    result = await db.sessions.update_one(
        {
            "_id": _oid(session_id),
            "status": "active",
            "is_deleted": {"$ne": True},
            "$expr": {
                "$lt": [
                    {"$ifNull": ["$reserved_seats", 0]},
                    {"$ifNull": ["$max_students", 0]},
                ],
            },
        },
        {"$inc": {"reserved_seats": 1}},
    )
    if result.modified_count != 1:
        return JSONResponse(status_code=409, content={"error": "session_full"})

    # Create active enrollment that remains pending admin approval.
    now = datetime.now(timezone.utc).isoformat()
    enrollment_doc = {
        "session_id": session_id,
        "student_id": entry["student_id"],
        "parent_user_id": entry.get("parent_user_id"),
        "billing_type": "Standard",
        "approval_status": "pending",
        "status": "active",
        "enrolled_at": now,
        "created_at": now,
        "is_deleted": False,
    }
    enrollment_result = await db.enrollments.insert_one(enrollment_doc)
    enrollment_id = str(enrollment_result.inserted_id)

    # Mark waitlist entry as enrolled
    await db.waitlist.update_one(
        {"_id": entry["_id"]},
        {"$set": {
            "status": "enrolled",
            "enrollment_id": enrollment_id,
            "enrolled_at": now,
        }},
    )

    # Audit log
    summary = f"session {session_id}, parent {entry.get('parent_user_id')}"
    await log_audit(admin, "waitlist.enrolled", "waitlist", waitlist_id, summary)

    return {"enrollment_id": enrollment_id, "waitlist_id": waitlist_id, "status": "enrolled"}


@router.post("/admin/waitlist/{waitlist_id}/skip")
async def admin_skip_waitlist(waitlist_id: str, body: _SkipBody = _SkipBody(), admin=Depends(require_roles("admin"))):
    """Mark a waitlist entry as skipped (no seat consumed)."""
    db = get_db()
    entry = await db.waitlist.find_one({"_id": _oid(waitlist_id), "is_deleted": {"$ne": True}})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    now = datetime.now(timezone.utc).isoformat()
    update = {"status": "skipped", "skipped_at": now}
    if body.skipped_reason is not None:
        update["skipped_reason"] = body.skipped_reason

    await db.waitlist.update_one({"_id": entry["_id"]}, {"$set": update})

    await log_audit(
        admin,
        "waitlist.skipped",
        "waitlist",
        waitlist_id,
        f"session {entry.get('session_id')}, parent {entry.get('parent_user_id')}",
    )

    updated = await db.waitlist.find_one({"_id": entry["_id"]})
    updated["id"] = str(updated.pop("_id"))
    return updated


@router.delete("/admin/waitlist/{waitlist_id}")
async def admin_remove_waitlist(waitlist_id: str, removed_reason: Optional[str] = None, admin=Depends(require_roles("admin"))):
    """Soft-delete a waitlist entry (status=removed, never hard-deleted)."""
    db = get_db()
    entry = await db.waitlist.find_one({"_id": _oid(waitlist_id), "is_deleted": {"$ne": True}})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    now = datetime.now(timezone.utc).isoformat()
    update = {"status": "removed", "removed_at": now}
    if removed_reason is not None:
        update["removed_reason"] = removed_reason

    await db.waitlist.update_one({"_id": entry["_id"]}, {"$set": update})

    await log_audit(
        admin,
        "waitlist.removed",
        "waitlist",
        waitlist_id,
        f"session {entry.get('session_id')}, parent {entry.get('parent_user_id')}",
    )

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Existing parent/legacy endpoints below
# ---------------------------------------------------------------------------


@router.post("/waitlist/{wid}/enroll")
async def enroll_waitlist_entry(wid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    entry = await db.waitlist.find_one({"_id": _oid(wid), "is_deleted": {"$ne": True}})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    if entry.get("status") == "offered" and entry.get("offer_expires_at"):
        expires = datetime.fromisoformat(entry["offer_expires_at"])
        if expires.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            await db.waitlist.update_one({"_id": entry["_id"]}, {"$set": {"status": "expired"}})
            raise HTTPException(status_code=400, detail="Waitlist offer expired")
    enrollment_id, doc = await enroll_waitlist_offer(db, wid, actor_role="admin")
    await log_audit(admin, "enroll", "waitlist", wid, enrollment_id)
    return {"enrollment_id": enrollment_id, **doc}
