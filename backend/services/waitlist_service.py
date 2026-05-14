"""Waitlist helpers for full sessions."""
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import HTTPException

from services.enrollment_service import create_enrollment_with_capacity, reserve_session_seat


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


ACTIVE_WAITLIST_STATUSES = {"waiting", "offered"}


async def join_waitlist(db, *, session_id: str, student: dict, requested_by: str) -> tuple[str, dict]:
    session = await db.sessions.find_one({"_id": _oid(session_id), "status": "active", "is_deleted": {"$ne": True}})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    student_id = str(student["_id"])
    existing = await db.waitlist.find_one({
        "session_id": session_id,
        "student_id": student_id,
        "status": {"$in": list(ACTIVE_WAITLIST_STATUSES)},
        "is_deleted": {"$ne": True},
    })
    if existing:
        return str(existing["_id"]), existing

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "session_id": session_id,
        "student_id": student_id,
        "parent_user_id": student.get("parent_user_id"),
        "status": "waiting",
        "requested_by": requested_by,
        "requested_at": now,
        "offer_expires_at": None,
        "offered_at": None,
        "enrolled_at": None,
        "is_deleted": False,
    }
    result = await db.waitlist.insert_one(doc)
    return str(result.inserted_id), doc


async def promote_next_waitlist(db, session_id: str, *, offer_hours: int = 48) -> dict | None:
    next_entry = await db.waitlist.find_one({
        "session_id": session_id,
        "status": "waiting",
        "is_deleted": {"$ne": True},
    }, sort=[("requested_at", 1)])
    if not next_entry:
        return None
    try:
        await reserve_session_seat(db, session_id)
    except HTTPException:
        return None
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=offer_hours)
    result = await db.waitlist.update_one(
        {"_id": next_entry["_id"], "status": "waiting"},
        {"$set": {
            "status": "offered",
            "offered_at": now.isoformat(),
            "offer_expires_at": expires_at.isoformat(),
        }},
    )
    if result.modified_count != 1:
        from services.enrollment_service import release_session_seat
        await release_session_seat(db, session_id)
        return None
    next_entry["status"] = "offered"
    next_entry["offered_at"] = now.isoformat()
    next_entry["offer_expires_at"] = expires_at.isoformat()
    return next_entry


async def enroll_waitlist_offer(db, waitlist_id: str, *, actor_role: str = "admin") -> tuple[str, dict]:
    entry = await db.waitlist.find_one({"_id": _oid(waitlist_id), "is_deleted": {"$ne": True}})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    if entry.get("status") not in {"offered", "waiting"}:
        raise HTTPException(status_code=400, detail="Waitlist entry is not enrollable")
    student = await db.students.find_one({"_id": _oid(entry["student_id"]), "is_deleted": {"$ne": True}})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    seat_reserved = entry.get("status") == "offered"
    enrollment_id, doc = await create_enrollment_with_capacity(
        db,
        session_id=entry["session_id"],
        student=student,
        actor_role=actor_role,
        billing_type="Standard",
        seat_reserved=seat_reserved,
    )
    await db.waitlist.update_one(
        {"_id": entry["_id"]},
        {"$set": {
            "status": "enrolled",
            "enrollment_id": enrollment_id,
            "enrolled_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return enrollment_id, doc
