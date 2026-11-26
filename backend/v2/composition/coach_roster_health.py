"""Children's health notes and emergency contacts for one class date (S49, D-14).

The owner's decision D-14: the coaches assigned to a class (lead, cover,
assistants) may read each child's medical note, emergency contact and parent
phone; the front-desk Today sheet reads the same facts. It is children's
health data, so it lives ONLY behind the two routes that serve it
(``GET /coach/roster-health`` and ``GET /admin/today/roster-health``), each
sent with ``Cache-Control: no-store``. It is deliberately absent from
``CoachRosterEntry``, the coach Today payload and teaching-plan rows: the
service worker caches every ``GET /api/v2/coach/(today|sessions)`` for 24h
and the query persister writes coach reads to localStorage. Never feed it to
lists, exports, digests, push, emails or AI prompts.

Kept out of ``composition/coach.py`` and ``composition/admin.py``; wired from
``main.py`` as ``app.state.coach_roster_health``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from bson import ObjectId

from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.get_occurrence_roster import (
    GetOccurrenceRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.profile.completeness import MEDICAL_NONE_SENTINEL
from backend.v2.shared.tenancy.context import current_academy_id

HealthStatus = Literal["declared", "none_declared", "not_answered"]


@dataclass(frozen=True)
class ChildHealth:
    student_id: str
    full_name: str
    #: ``none_declared`` (the parent ticked "no known conditions") is a
    #: different answer from ``not_answered`` (never asked), so a missing
    #: note is never read as "nothing to know".
    status: HealthStatus
    note: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    parent_name: str | None = None
    parent_phone: str | None = None


def _text(value: object) -> str | None:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


def health_status(raw_note: object) -> tuple[HealthStatus, str | None]:
    """Map the stored ``medical_notes`` value to a status and the note text."""
    note = _text(raw_note)
    if note is None:
        return "not_answered", None
    if note == MEDICAL_NONE_SENTINEL:
        return "none_declared", None
    return "declared", note


def is_assigned(occurrence: SessionOccurrence, user_id: str) -> bool:
    """Lead (scheduled or actual), cover (substitute) or a listed assistant.

    The same four fields ``list_for_coach_on_date`` puts a class on a coach's
    Today with, so "it is on my Today" and "I may read its health notes" agree.
    """
    staff = {
        occurrence.scheduled_coach_id,
        occurrence.actual_coach_id,
        occurrence.substitute_coach_id,
        *occurrence.assistant_coach_ids,
    }
    return bool(user_id) and user_id in staff


class RosterHealthReader:
    """One batched read of a class date's children's health facts.

    Every read is tenant scoped: the occurrence through its repository, the
    students by ``academy_id``; parents are looked up only by the ids those
    tenant-scoped student rows name.
    """

    def __init__(
        self,
        db: Any,
        *,
        occurrences: MongoSessionOccurrenceRepository,
        roster: GetOccurrenceRoster,
    ) -> None:
        self._db = db
        self._occurrences = occurrences
        self.roster = roster

    async def occurrence(self, occurrence_id: str) -> SessionOccurrence | None:
        return await self._occurrences.get(occurrence_id)

    async def for_occurrence(self, occurrence: SessionOccurrence) -> list[ChildHealth]:
        """Every child on that date's roster, in roster order."""
        roster = await self.roster.execute(
            session_id=occurrence.template_session_id or occurrence.session_id,
            occurrence_id=occurrence.occurrence_id,
        )
        facts = await self.for_students([r.student_id for r in roster])
        return [
            facts.get(r.student_id) or ChildHealth(r.student_id, r.full_name, "not_answered")
            for r in roster
        ]

    async def for_students(self, student_ids: Sequence[str]) -> dict[str, ChildHealth]:
        ids = [sid for sid in dict.fromkeys(student_ids) if sid]
        if not ids:
            return {}
        object_ids = [ObjectId(sid) for sid in ids if ObjectId.is_valid(sid)]
        cursor = self._db["students"].find(
            {
                "academy_id": current_academy_id(),
                "$or": [{"student_id": {"$in": ids}}, {"_id": {"$in": object_ids}}],
            },
            {
                "student_id": 1,
                "full_name": 1,
                "first_name": 1,
                "last_name": 1,
                "medical_notes": 1,
                "emergency_contact_name": 1,
                "emergency_contact_phone": 1,
                "parent_id": 1,
                "parent_user_id": 1,
            },
        )
        docs = [doc async for doc in cursor]
        parents = await user_contacts(self._db, [parent_ref(d) for d in docs])
        out: dict[str, ChildHealth] = {}
        for doc in docs:
            student_id = str(doc.get("student_id") or doc.get("_id"))
            status, note = health_status(doc.get("medical_notes"))
            parent = parents.get(parent_ref(doc), {})
            name = _text(doc.get("full_name")) or _text(
                f"{doc.get('first_name') or ''} {doc.get('last_name') or ''}"
            )
            out[student_id] = ChildHealth(
                student_id=student_id,
                full_name=name or "Unnamed student",
                status=status,
                note=note,
                emergency_contact_name=_text(doc.get("emergency_contact_name")),
                emergency_contact_phone=_text(doc.get("emergency_contact_phone")),
                parent_name=parent.get("name"),
                parent_phone=parent.get("phone"),
            )
        return out


async def user_contacts(db: Any, user_ids: Sequence[str]) -> dict[str, dict[str, str | None]]:
    """``{user id: {"name", "phone"}}`` for ids taken from tenant-scoped
    rows (users are global; the ids are what keep this in the tenant)."""
    ids = [uid for uid in dict.fromkeys(user_ids) if uid]
    if not ids:
        return {}
    object_ids = [ObjectId(uid) for uid in ids if ObjectId.is_valid(uid)]
    cursor = db["users"].find(
        {"$or": [{"user_id": {"$in": ids}}, {"_id": {"$in": object_ids}}]},
        {"user_id": 1, "display_name": 1, "first_name": 1, "last_name": 1, "phone": 1},
    )
    out: dict[str, dict[str, str | None]] = {}
    async for user in cursor:
        name = _text(user.get("display_name")) or _text(
            f"{user.get('first_name') or ''} {user.get('last_name') or ''}"
        )
        facts = {"name": name, "phone": _text(user.get("phone"))}
        for key in (user.get("user_id"), user.get("_id")):
            if key:
                out[str(key)] = facts
    return out


def parent_ref(doc: dict[str, Any]) -> str:
    return str(doc.get("parent_id") or doc.get("parent_user_id") or "")


def compose_coach_roster_health(db: Any) -> RosterHealthReader:
    students = MongoStudentRepository(db)
    occurrences = MongoSessionOccurrenceRepository(db)
    roster = GetOccurrenceRoster(
        get_roster=GetSessionRoster(enrollments=MongoEnrollmentRepository(db), students=students),
        absence_notices=MongoAbsenceNoticeRepository(db),
        occurrence_roster=MongoOccurrenceRosterRepository(db),
        students=students,
        occurrences=occurrences,
        trial_outcomes=MongoTrialRequestRepository(db),
        marks=MongoAttendanceRepository(db),
    )
    return RosterHealthReader(db, occurrences=occurrences, roster=roster)
