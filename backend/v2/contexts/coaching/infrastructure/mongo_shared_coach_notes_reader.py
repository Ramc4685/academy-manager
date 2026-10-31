"""Mongo reader for the coach notes an admin sees on a family record.

Every tenant-owned read carries the request's ``academy_id``: the student must
belong to the academy (else ``None``, a 404 at the route), and only that
academy's ``progress_notes`` and ``sessions`` are read. Coach names come from
the global ``users`` collection, looked up only for coach ids that the
tenant-scoped notes named, with one equality lookup per id field (never an
``$or`` across fields).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from backend.v2.contexts.coaching.application.use_cases.shared_coach_notes import (
    SharedCoachNote,
)


def _display_name(user: dict[str, Any]) -> str | None:
    for field in ("full_name", "display_name", "name"):
        if user.get(field):
            return str(user[field])
    name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
    return name or None


def _aware(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


class MongoSharedCoachNotesReader:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def list_shared_for_student(
        self, *, academy_id: str, student_id: str, limit: int
    ) -> list[SharedCoachNote] | None:
        if not await self._student_exists(academy_id, student_id):
            return None
        cursor = (
            self._db["progress_notes"]
            .find({"academy_id": academy_id, "student_id": student_id, "visibility": "shared"})
            .sort([("created_at", -1)])
            .limit(limit)
        )
        docs = [doc async for doc in cursor]
        if not docs:
            return []
        session_ids = sorted({str(d["session_id"]) for d in docs if d.get("session_id")})
        titles: dict[str, str] = {}
        if session_ids:
            async for s in self._db["sessions"].find(
                {"academy_id": academy_id, "session_id": {"$in": session_ids}},
                {"session_id": 1, "title": 1},
            ):
                titles[str(s["session_id"])] = str(s.get("title") or "Session")
        coach_names = await self._coach_names(
            academy_id, sorted({str(d["coach_id"]) for d in docs if d.get("coach_id")})
        )
        return [
            SharedCoachNote(
                note_id=str(d.get("note_id") or d["_id"]),
                student_id=student_id,
                session_id=str(d["session_id"]) if d.get("session_id") else None,
                session_title=titles.get(str(d.get("session_id"))),
                coach_id=str(d["coach_id"]) if d.get("coach_id") else None,
                coach_name=coach_names.get(str(d.get("coach_id"))),
                body=str(d.get("body") or d.get("note") or ""),
                created_at=_aware(d.get("created_at")),
            )
            for d in docs
        ]

    async def _student_exists(self, academy_id: str, student_id: str) -> bool:
        """``student_id`` first, then a legacy ObjectId ``_id`` (sequential
        equality lookups, never an ``$or``)."""
        found = await self._db["students"].find_one(
            {"academy_id": academy_id, "student_id": student_id}, {"_id": 1}
        )
        if found is None and ObjectId.is_valid(student_id):
            found = await self._db["students"].find_one(
                {"academy_id": academy_id, "_id": ObjectId(student_id)}, {"_id": 1}
            )
        return found is not None

    async def _coach_names(self, academy_id: str, coach_ids: list[str]) -> dict[str, str]:
        """Names for coach ids the academy's own notes named (``academy_id``
        scopes which ids are asked about; ``users`` itself is global)."""
        names: dict[str, str] = {}
        for field in ("user_id", "firebase_uid"):
            missing = [cid for cid in coach_ids if cid not in names]
            if not missing:
                break
            async for user in self._db["users"].find(
                {field: {"$in": missing}},
                {
                    "user_id": 1,
                    "firebase_uid": 1,
                    "full_name": 1,
                    "display_name": 1,
                    "name": 1,
                    "first_name": 1,
                    "last_name": 1,
                },
            ):
                name = _display_name(user)
                key = str(user.get(field) or "")
                if name and key:
                    names[key] = name
        return names
