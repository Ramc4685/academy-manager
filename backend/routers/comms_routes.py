"""Messages + Notifications."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from models import MessageIn
from auth import get_current_user
from db import get_db
from services.enrollment_service import APPROVED_ENROLLMENT_APPROVAL_STATUS

router = APIRouter()


def _thread_id(a: str, b: str) -> str:
    return ":".join(sorted([a, b]))


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


async def _allowed_contact_ids(db, user: dict) -> set[str]:
    """Return user ids the current user may message."""
    if user["role"] == "admin":
        users = await db.users.find(
            {"_id": {"$ne": ObjectId(user["id"])}, "status": {"$ne": "deleted"}},
            {"_id": 1},
        ).to_list(2000)
        return {str(u["_id"]) for u in users}

    admins = await db.users.find(
        {"role": "admin", "status": {"$ne": "deleted"}},
        {"_id": 1},
    ).to_list(100)
    allowed = {str(u["_id"]) for u in admins if str(u["_id"]) != user["id"]}

    if user["role"] == "coach":
        sessions = await db.sessions.find(
            {"coach_id": user["id"], "is_deleted": {"$ne": True}},
            {"_id": 1},
        ).to_list(500)
        session_ids = [str(s["_id"]) for s in sessions]
        enrolls = await db.enrollments.find(
            {
                "session_id": {"$in": session_ids},
                "status": "active",
                "approval_status": APPROVED_ENROLLMENT_APPROVAL_STATUS,
                "is_deleted": {"$ne": True},
            },
            {"parent_user_id": 1},
        ).to_list(2000)
        allowed.update(e["parent_user_id"] for e in enrolls if e.get("parent_user_id"))
    elif user["role"] == "parent":
        students = await db.students.find(
            {"parent_user_id": user["id"], "is_deleted": {"$ne": True}},
            {"_id": 1},
        ).to_list(50)
        student_ids = [str(s["_id"]) for s in students]
        enrolls = await db.enrollments.find(
            {
                "student_id": {"$in": student_ids},
                "status": "active",
                "approval_status": APPROVED_ENROLLMENT_APPROVAL_STATUS,
                "is_deleted": {"$ne": True},
            },
            {"session_id": 1},
        ).to_list(500)
        session_ids = list({e["session_id"] for e in enrolls})
        if session_ids:
            async for s in db.sessions.find(
                {"_id": {"$in": [ObjectId(x) for x in session_ids]}, "is_deleted": {"$ne": True}},
                {"coach_id": 1},
            ):
                if s.get("coach_id"):
                    allowed.add(s["coach_id"])

    allowed.discard(user["id"])
    return allowed


# ----------------- /api/messages/contacts -----------------
@router.get("/messages/contacts")
async def list_contacts(user=Depends(get_current_user)):
    """Return the list of users this person is allowed to message."""
    db = get_db()
    if user["role"] == "admin":
        allowed = await _allowed_contact_ids(db, user)
    elif user["role"] in ("coach", "parent"):
        allowed = await _allowed_contact_ids(db, user)
    else:
        return []
    if not allowed:
        return []
    items = await db.users.find(
        {"_id": {"$in": [ObjectId(uid) for uid in allowed]}, "status": {"$ne": "deleted"}},
        {"password_hash": 0},
    ).to_list(2000)
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


# ----------------- /api/messages -----------------
@router.get("/messages/threads")
async def list_threads(user=Depends(get_current_user)):
    db = get_db()
    cursor = db.messages.find({"$or": [{"from_user_id": user["id"]}, {"to_user_id": user["id"]}]}).sort("created_at", -1)
    msgs = await cursor.to_list(2000)
    threads: dict = {}
    other_ids = set()
    for m in msgs:
        other = m["to_user_id"] if m["from_user_id"] == user["id"] else m["from_user_id"]
        other_ids.add(other)
        if other not in threads:
            threads[other] = {
                "other_user_id": other,
                "last_message": m["body"],
                "last_at": m["created_at"],
                "unread": 0,
            }
        if m["to_user_id"] == user["id"] and not m.get("read"):
            threads[other]["unread"] += 1
    users = {}
    if other_ids:
        async for u in db.users.find({"_id": {"$in": [ObjectId(x) for x in other_ids]}}):
            users[str(u["_id"])] = {"name": u.get("name", u.get("email")), "role": u.get("role")}
    result = []
    for oid, t in threads.items():
        t["other_user"] = users.get(oid, {"name": "Unknown", "role": ""})
        result.append(t)
    result.sort(key=lambda x: x["last_at"], reverse=True)
    return result


@router.get("/messages/thread/{other_user_id}")
async def get_thread(other_user_id: str, user=Depends(get_current_user)):
    db = get_db()
    other = await db.users.find_one({"_id": _oid(other_user_id), "status": {"$ne": "deleted"}})
    if not other:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if other_user_id not in await _allowed_contact_ids(db, user):
        raise HTTPException(status_code=403, detail="Forbidden")
    tid = _thread_id(user["id"], other_user_id)
    cursor = db.messages.find({"thread_id": tid}).sort("created_at", 1)
    msgs = await cursor.to_list(2000)
    # Mark received messages as read
    await db.messages.update_many(
        {"thread_id": tid, "to_user_id": user["id"], "read": False},
        {"$set": {"read": True}},
    )
    for m in msgs:
        m["id"] = str(m.pop("_id"))
    return msgs


@router.post("/messages")
async def send_message(body: MessageIn, user=Depends(get_current_user)):
    db = get_db()
    other = await db.users.find_one({"_id": _oid(body.to_user_id), "status": {"$ne": "deleted"}})
    if not other:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if body.to_user_id not in await _allowed_contact_ids(db, user):
        raise HTTPException(status_code=403, detail="Forbidden")
    tid = _thread_id(user["id"], body.to_user_id)
    doc = {
        "thread_id": tid,
        "from_user_id": user["id"],
        "to_user_id": body.to_user_id,
        "body": body.body,
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = await db.messages.insert_one(doc)
    # Create notification for recipient
    await db.notifications.insert_one({
        "user_id": body.to_user_id,
        "type": "message",
        "title": f"New message from {user.get('name', user.get('email'))}",
        "message": body.body[:120],
        "related_entity": str(r.inserted_id),
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    doc.pop("_id", None)
    doc["id"] = str(r.inserted_id)
    return doc


# ----------------- /api/notifications -----------------
@router.get("/notifications")
async def list_notifications(user=Depends(get_current_user)):
    db = get_db()
    cursor = db.notifications.find({"user_id": user["id"]}).sort("created_at", -1).limit(100)
    items = await cursor.to_list(100)
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


@router.patch("/notifications/{nid}/read")
async def mark_notif_read(nid: str, user=Depends(get_current_user)):
    db = get_db()
    await db.notifications.update_one(
        {"_id": ObjectId(nid), "user_id": user["id"]},
        {"$set": {"read": True}},
    )
    return {"ok": True}


@router.post("/notifications/read-all")
async def mark_all_read(user=Depends(get_current_user)):
    db = get_db()
    r = await db.notifications.update_many({"user_id": user["id"], "read": False}, {"$set": {"read": True}})
    return {"updated": r.modified_count}
