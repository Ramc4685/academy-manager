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
