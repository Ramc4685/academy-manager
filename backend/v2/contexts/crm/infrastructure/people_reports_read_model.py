"""Mongo reads behind the L5b People reports (attendance risk, families lost).

Every query carries ``academy_id`` explicitly; nothing here reads the tenant
ContextVar, so a report always reads the academy it was asked for.

* :class:`MongoAttendanceRiskSource`: the academy's students, their lifecycle
  snapshots from the enrollment context's own derivation (the port the family
  index reads), the classes they hold seats in and those classes' coaches.
  A fixed number of reads however large the academy is.
* :class:`MongoDepartureSource`: departure events from ``enrollment_events``
  on the ``enrollment_event_type_effective`` index (migration 0090:
  ``academy_id, event_type, effective_at``). No new index.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.crm.application.people_reports import (
    DEPARTURE_TRANSITIONS,
    AttendanceRiskFacts,
    DepartureFact,
    RiskClass,
    RiskStudent,
)
from backend.v2.contexts.crm.application.ports import ChildLifecycleReader

CoachNames = Callable[[str, Sequence[str]], Awaitable[Mapping[str, str]]]


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class MongoAttendanceRiskSource:
    def __init__(self, db: Any, *, children: ChildLifecycleReader, coach_names: CoachNames) -> None:
        self._db = db
        self._children = children
        self._coach_names = coach_names

    async def facts(self, academy_id: str) -> AttendanceRiskFacts:
        student_ids = [
            str(doc["student_id"])
            async for doc in self._db["students"].find(
                {"academy_id": academy_id, "is_deleted": {"$ne": True}},
                {"_id": 0, "student_id": 1},
            )
            if doc.get("student_id")
        ]
        snapshots = await self._children.lifecycle_snapshots(
            academy_id=academy_id, student_ids=student_ids
        )
        students = tuple(
            RiskStudent(
                student_id=student_id,
                state=snap.state,
                live_session_ids=tuple(snap.live_session_ids),
            )
            for student_id, snap in snapshots.items()
        )
        session_ids = sorted({sid for s in students for sid in s.live_session_ids})
        classes: dict[str, RiskClass] = {}
        if session_ids:
            async for doc in self._db["sessions"].find(
                {"academy_id": academy_id, "session_id": {"$in": session_ids}},
                {"_id": 0, "session_id": 1, "title": 1, "name": 1, "coach_id": 1},
            ):
                session_id = str(doc["session_id"])
                classes[session_id] = RiskClass(
                    session_id=session_id,
                    title=_opt_str(doc.get("title")) or _opt_str(doc.get("name")) or session_id,
                    coach_id=_opt_str(doc.get("coach_id")),
                )
        coach_ids = sorted({c.coach_id for c in classes.values() if c.coach_id})
        names = await self._coach_names(academy_id, coach_ids) if coach_ids else {}
        return AttendanceRiskFacts(students=students, classes=classes, coach_names=dict(names))


class MongoDepartureSource:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def departures(
        self, academy_id: str, *, effective_from: datetime, effective_before: datetime
    ) -> list[DepartureFact]:
        cursor = self._db["enrollment_events"].find(
            {
                "academy_id": academy_id,
                "event_type": {"$in": sorted(DEPARTURE_TRANSITIONS)},
                "effective_at": {"$gte": effective_from, "$lt": effective_before},
            },
            {"_id": 0, "student_id": 1, "event_type": 1, "reason_code": 1, "effective_at": 1},
        )
        facts: list[DepartureFact] = []
        async for doc in cursor:
            student_id = _opt_str(doc.get("student_id"))
            effective_at = doc.get("effective_at")
            if student_id is None or not isinstance(effective_at, datetime):
                continue
            facts.append(
                DepartureFact(
                    student_id=student_id,
                    event_type=str(doc.get("event_type") or ""),
                    reason_code=_opt_str(doc.get("reason_code")),
                    effective_at=_as_utc(effective_at),
                )
            )
        return facts
