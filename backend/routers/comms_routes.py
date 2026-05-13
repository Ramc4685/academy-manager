"""Messages + Notifications."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from models import MessageIn
from auth import get_current_user
from db import get_db

router = APIRouter()


def _thread_id(a: str, b: str) -> str:
    return ":".join(sorted([a, b]))


# ----------------- /api/messages/contacts -----------------
@router.get("/messages/contacts")
async def list_contacts(user=Depends(get_current_user)):
    """Return the list of users this person is allowed to message."""
    db = get_db()
    if user["role"] == "admin":
        cursor = db.users.find(
            {"_id": {"$ne": ObjectId(user["id"])}, "status": {"$ne": "deleted"}},
            {"password_hash": 0},
        )
    elif user["role"] == "coach":
        # Coaches see admins + parents of students in their sessions
        sessions = await db.sessions.find({"coach_id": user["id"]}, {"_id": 1}).to_list(500)
        sids = [str(s["_id"]) for s in sessions]
        enrolls = await db.enrollments.find(
            {"session_id": {"$in": sids}, "status": "active"}, {"parent_user_id": 1},
        ).to_list(2000)
        parent_ids = list({e["parent_user_id"] for e in enrolls if e.get("parent_user_id")})
        admins = [u async for u in db.users.find({"role": "admin", "status": {"$ne": "deleted"}}, {"password_hash": 0})]
        parents = []
        if parent_ids:
            parents = [u async for u in db.users.find(
                {"_id": {"$in": [ObjectId(p) for p in parent_ids]}, "status": {"$ne": "deleted"}},
                {"password_hash": 0},
            )]
        items = admins + parents
        for it in items:
            it["id"] = str(it.pop("_id"))
        return items
    elif user["role"] == "parent":
        # Parents see admins + coaches of their kids' sessions
        students = await db.students.find({"parent_user_id": user["id"]}, {"_id": 1}).to_list(50)
        sids = [str(s["_id"]) for s in students]
        enrolls = await db.enrollments.find(
            {"student_id": {"$in": sids}, "status": "active"}, {"session_id": 1},
        ).to_list(500)
        sess_ids = list({e["session_id"] for e in enrolls})
        coach_ids = set()
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in sess_ids]}}, {"coach_id": 1}):
            if s.get("coach_id"):
                coach_ids.add(s["coach_id"])
        admins = [u async for u in db.users.find({"role": "admin", "status": {"$ne": "deleted"}}, {"password_hash": 0})]
        coaches = []
        if coach_ids:
            coaches = [u async for u in db.users.find(
                {"_id": {"$in": [ObjectId(c) for c in coach_ids]}}, {"password_hash": 0},
            )]
        items = admins + coaches
        for it in items:
            it["id"] = str(it.pop("_id"))
        return items
    else:
        return []
    items = await cursor.to_list(2000)
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
    other = await db.users.find_one({"_id": ObjectId(body.to_user_id)})
    if not other:
        raise HTTPException(status_code=404, detail="Recipient not found")
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
