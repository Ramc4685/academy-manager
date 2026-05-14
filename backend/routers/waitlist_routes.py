"""Waitlist routes."""
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user, require_roles, log_audit
from db import get_db
from models import EnrollmentIn
from services.waitlist_service import enroll_waitlist_offer, join_waitlist

router = APIRouter()


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
