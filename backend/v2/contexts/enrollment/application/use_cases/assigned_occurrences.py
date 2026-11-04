"""Query: resolve the class behind an approved make-up / trial (issue #1038).

Parent request DTOs used to carry only ``approved_target_occurrence_id`` /
``assigned_occurrence_id`` — a raw id a family cannot act on. This resolves
those ids to the facts a parent needs to turn up: class name, start/end
instant, location and the occurrence's own status (so a cancelled class is
shown as cancelled, never as "attend here").

The caller only ever passes occurrence ids taken from the requesting parent's
own requests, and both reads are tenant-scoped by the repositories, so one
family cannot use this to look at another family's or academy's classes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence


class _OccurrenceBatchQuery(Protocol):
    async def get_many(self, occurrence_ids: list[str]) -> list[SessionOccurrence]: ...


class _SessionBatchQuery(Protocol):
    async def get_many(self, session_ids: list[str]) -> list[Session]: ...


class AssignedOccurrence(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    session_title: str
    location: str | None = None
    start_at: datetime
    end_at: datetime
    status: str


class ResolveAssignedOccurrences:
    def __init__(
        self,
        *,
        occurrences: _OccurrenceBatchQuery,
        sessions: _SessionBatchQuery,
    ) -> None:
        self._occurrences = occurrences
        self._sessions = sessions

    async def execute(self, occurrence_ids: list[str]) -> dict[str, AssignedOccurrence]:
        """Map each resolvable occurrence id to its class facts.

        Ids that no longer resolve (occurrence dropped) are simply absent —
        the caller renders "details unavailable" rather than inventing them.
        """
        wanted = list(dict.fromkeys(oid for oid in occurrence_ids if oid))
        if not wanted:
            return {}
        occurrences = await self._occurrences.get_many(wanted)
        session_ids = list(
            dict.fromkeys(
                sid
                for occ in occurrences
                for sid in (occ.template_session_id, occ.session_id)
                if sid
            )
        )
        sessions = (
            {s.session_id: s for s in await self._sessions.get_many(session_ids)}
            if session_ids
            else {}
        )
        resolved: dict[str, AssignedOccurrence] = {}
        for occ in occurrences:
            session = next(
                (
                    sessions[sid]
                    for sid in (occ.template_session_id, occ.session_id)
                    if sid and sid in sessions
                ),
                None,
            )
            resolved[occ.occurrence_id] = AssignedOccurrence(
                occurrence_id=occ.occurrence_id,
                session_id=session.session_id if session else occ.session_id,
                session_title=session.title if session else "Session",
                location=session.location if session else None,
                start_at=occ.start_at,
                end_at=occ.end_at,
                status=occ.status,
            )
        return resolved
