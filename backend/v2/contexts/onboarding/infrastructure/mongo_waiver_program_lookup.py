"""Which program a class or a child belongs to, for waiver assignment.

A program groups classes for the public page (``sessions.program_id``, owned by
Enrollment). Waiver assignment only needs to read that link, so this adapter
reads ``sessions``, ``enrollments`` and ``programs`` directly, tenant-filtered
on every query, instead of importing the Enrollment context.

Live enrollments here are the same set the parent waiver prompt uses
(``active`` and ``paused``): a waiver is owed for a class the child still
attends. Session ids are looked up with equality/``$in`` filters per field,
never one ``$or`` (#878, #894).
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    ProgramRef,
)
from backend.v2.shared.tenancy import current_academy_id

_LIVE_ENROLLMENT_STATUSES = ("active", "paused")


class MongoWaiverProgramLookup:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def list_programs(self) -> list[ProgramRef]:
        cursor = self._db["programs"].find(
            {"academy_id": current_academy_id(), "archived": {"$ne": True}},
            sort=[("sort_order", 1)],
        )
        return [
            ProgramRef(program_id=str(doc["program_id"]), name=str(doc.get("name") or "Program"))
            async for doc in cursor
            if doc.get("program_id")
        ]

    async def list_archived_programs(self) -> list[ProgramRef]:
        cursor = self._db["programs"].find(
            {"academy_id": current_academy_id(), "archived": True},
            sort=[("sort_order", 1)],
        )
        return [
            ProgramRef(
                program_id=str(doc["program_id"]),
                name=str(doc.get("name") or "Program"),
                archived=True,
            )
            async for doc in cursor
            if doc.get("program_id")
        ]

    async def program_id_for_session(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        return (await self._program_ids_by_session([session_id])).get(session_id)

    async def program_ids_for_students(self, student_ids: list[str]) -> dict[str, set[str]]:
        """Program ids of each student's live classes (a student can be in several)."""
        out: dict[str, set[str]] = {student_id: set() for student_id in student_ids}
        if not student_ids:
            return out
        cursor = self._db["enrollments"].find(
            {
                "academy_id": current_academy_id(),
                "student_id": {"$in": student_ids},
                "status": {"$in": list(_LIVE_ENROLLMENT_STATUSES)},
            },
            {"student_id": 1, "session_id": 1},
        )
        pairs = [
            (str(doc.get("student_id")), str(doc.get("session_id")))
            async for doc in cursor
            if doc.get("session_id")
        ]
        by_session = await self._program_ids_by_session(sorted({sid for _, sid in pairs}))
        for student_id, session_id in pairs:
            program_id = by_session.get(session_id)
            if program_id:
                out.setdefault(student_id, set()).add(program_id)
        return out

    async def _program_ids_by_session(self, session_ids: list[str]) -> dict[str, str]:
        if not session_ids:
            return {}
        academy_id = current_academy_id()
        sessions = self._db["sessions"]
        found: dict[str, str] = {}
        cursor = sessions.find(
            {"academy_id": academy_id, "session_id": {"$in": session_ids}},
            {"session_id": 1, "program_id": 1},
        )
        async for doc in cursor:
            if doc.get("program_id"):
                found[str(doc.get("session_id"))] = str(doc["program_id"])
        legacy = [sid for sid in session_ids if BsonObjectId.is_valid(sid)]
        if legacy:
            cursor = sessions.find(
                {"academy_id": academy_id, "_id": {"$in": [BsonObjectId(sid) for sid in legacy]}},
                {"program_id": 1},
            )
            async for doc in cursor:
                if doc.get("program_id"):
                    found.setdefault(str(doc["_id"]), str(doc["program_id"]))
        return found
