"""Shared enrollment capacity and creation helpers."""
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from pymongo import ReturnDocument


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


async def get_enrollable_session(db, session_id: str) -> dict:
    session = await db.sessions.find_one({"_id": _oid(session_id), "is_deleted": {"$ne": True}})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("status") != "active":
        raise HTTPException(status_code=400, detail="Session is not open for enrollment")
    return session


async def capacity_snapshot(db, session: dict) -> dict:
    session_id = str(session["_id"])
    max_students = int(session.get("max_students", 0) or 0)
    active_count = await db.enrollments.count_documents({
        "session_id": session_id,
        "status": "active",
        "is_deleted": {"$ne": True},
    })
    active_enrollments = max(active_count, int(session.get("reserved_seats", 0) or 0))
    available_seats = max(max_students - active_enrollments, 0)
    return {
        "max_students": max_students,
        "active_enrollments": active_enrollments,
        "available_seats": available_seats,
        "is_full": active_enrollments >= max_students if max_students > 0 else True,
    }


async def ensure_capacity_available(db, session_id: str) -> tuple[dict, dict]:
    session = await get_enrollable_session(db, session_id)
    snapshot = await capacity_snapshot(db, session)
    if snapshot["is_full"]:
        raise HTTPException(status_code=400, detail="Session is full")
    return session, snapshot


async def _initialize_reserved_seats(db, session_id: str) -> None:
    active_enrollments = await db.enrollments.count_documents({
        "session_id": session_id,
        "status": "active",
        "is_deleted": {"$ne": True},
    })
    await db.sessions.update_one(
        {"_id": _oid(session_id), "reserved_seats": {"$exists": False}},
        {"$set": {"reserved_seats": active_enrollments}},
    )


async def initialize_reserved_seats(db, session_id: str) -> None:
    await _initialize_reserved_seats(db, session_id)


async def reserve_session_seat(db, session_id: str) -> dict:
    await get_enrollable_session(db, session_id)
    await _initialize_reserved_seats(db, session_id)
    session = await db.sessions.find_one_and_update(
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
        return_document=ReturnDocument.AFTER,
    )
    if not session:
        raise HTTPException(status_code=400, detail="Session is full")
    return session


async def release_session_seat(db, session_id: str) -> None:
    await _initialize_reserved_seats(db, session_id)
    await db.sessions.update_one(
        {"_id": _oid(session_id)},
        [
            {
                "$set": {
                    "reserved_seats": {
                        "$max": [
                            {"$subtract": [{"$ifNull": ["$reserved_seats", 0]}, 1]},
                            0,
                        ],
                    },
                },
            },
        ],
    )


async def create_enrollment_with_capacity(
    db,
    *,
    session_id: str,
    student: dict,
    actor_role: str,
    billing_type: str = "Standard",
    seat_reserved: bool = False,
    approval_status: str | None = None,
) -> tuple[str, dict]:
    student_id = str(student["_id"])
    existing = await db.enrollments.find_one({
        "session_id": session_id,
        "student_id": student_id,
        "is_deleted": {"$ne": True},
    })
    if existing and existing.get("status") == "active":
        raise HTTPException(status_code=400, detail="Already enrolled")
    if not seat_reserved:
        await reserve_session_seat(db, session_id)

    doc = {
        "session_id": session_id,
        "student_id": student_id,
        "parent_user_id": student.get("parent_user_id"),
        "billing_type": billing_type or "Standard",
        "approval_status": approval_status or ("approved" if actor_role == "admin" else "pending"),
        "status": "active",
        "enrolled_at": datetime.now(timezone.utc).isoformat(),
        "is_deleted": False,
    }
    try:
        if existing:
            result = await db.enrollments.update_one(
                {"_id": existing["_id"], "status": {"$ne": "active"}},
                {"$set": doc},
            )
            if result.modified_count != 1:
                if not seat_reserved:
                    await release_session_seat(db, session_id)
                raise HTTPException(status_code=400, detail="Already enrolled")
            enrollment_id = str(existing["_id"])
        else:
            result = await db.enrollments.insert_one(doc)
            enrollment_id = str(result.inserted_id)
    except DuplicateKeyError:
        if not seat_reserved:
            await release_session_seat(db, session_id)
        raise HTTPException(status_code=400, detail="Already enrolled")
    except Exception:
        if not seat_reserved:
            await release_session_seat(db, session_id)
        raise
    return enrollment_id, doc
