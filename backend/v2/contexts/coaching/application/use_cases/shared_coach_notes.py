"""Coach notes an admin may read on a family record (People CRM A4, #665).

The family record's child drawer shows a child's coach notes read-only, with
the coach's name. The audience rule is #665's: a progress note is private to
coaches unless the coach shared it (``visibility == "shared"``), and a shared
note is the one a parent already sees in their feed. The admin drawer shows
exactly that set, so it never reveals a note the family could not see.

Skill notes are not included: #665 gave them no parent audience yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

#: The drawer shows the newest notes; the full history is the student page.
SHARED_COACH_NOTES_LIMIT: Final[int] = 20


@dataclass(frozen=True)
class SharedCoachNote:
    note_id: str
    student_id: str
    session_id: str | None
    session_title: str | None
    coach_id: str | None
    coach_name: str | None
    body: str
    created_at: datetime


class SharedCoachNotesReader(Protocol):
    async def list_shared_for_student(
        self, *, academy_id: str, student_id: str, limit: int
    ) -> list[SharedCoachNote] | None:
        """Shared notes, newest first; None when the student is not in this academy."""
        ...


class StudentNotInAcademy(LookupError):
    """The student id is not a student of the caller's academy."""


class ListSharedCoachNotes:
    def __init__(self, reader: SharedCoachNotesReader) -> None:
        self._reader = reader

    async def execute(
        self, *, academy_id: str, student_id: str, limit: int = SHARED_COACH_NOTES_LIMIT
    ) -> list[SharedCoachNote]:
        notes = await self._reader.list_shared_for_student(
            academy_id=academy_id,
            student_id=student_id,
            limit=max(1, min(limit, SHARED_COACH_NOTES_LIMIT)),
        )
        if notes is None:
            raise StudentNotInAcademy(student_id)
        return notes
