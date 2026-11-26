"""S44: tell a coach in the app when their teaching schedule changes.

Two halves, both here so ``composition/admin.py`` (at its line cap) is untouched:

* ``CoachScheduleNotices`` — called by the admin session routes AFTER their
  write. It diffs who teaches before and after and appends one
  ``CoachScheduleNoticeRequested`` outbox event per affected coach. It never
  raises: the schedule write already happened and a notice may not undo it.
* ``CoachScheduleNoticeDelivery`` + the ``@handler`` — the outbox handler. It
  writes one DM into the coach's inbox (the same ``messages`` store an admin's
  DM uses) and nudges their phone through the DM push path. The message id is
  derived from the event id, so a replayed event never writes a second message.

Tenancy: the academy is read at execution time (``current_academy_id()`` on
emit, ``tenant_scope(event.academy_id)`` on delivery), never captured here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from backend.v2.composition.roster_notifications import (
    format_occurrence_when,
    format_session_schedule,
)
from backend.v2.contexts.enrollment.domain.events import (
    CoachScheduleNoticeKind,
    CoachScheduleNoticePayload,
    CoachScheduleNoticeRequested,
)
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.comms import Message, MongoMessageRepository
from backend.v2.shared.events import handler
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.context import tenant_scope

log = logging.getLogger(__name__)

Role = Literal["lead", "assistant"]

#: Fields whose change means the class now runs at a different time or court.
_SCHEDULE_FIELDS = ("days_of_week", "start_time", "end_time", "timezone", "location")


def session_staff(session: Session | None) -> dict[str, Role]:
    if session is None:
        return {}
    staff: dict[str, Role] = {}
    if session.coach_id:
        staff[session.coach_id] = "lead"
    for uid in session.assistant_coach_ids:
        staff.setdefault(uid, "assistant")
    return staff


def occurrence_staff(occurrence: SessionOccurrence | None) -> dict[str, Role]:
    """Who teaches this date: actual coach, else substitute, else scheduled."""
    if occurrence is None:
        return {}
    staff: dict[str, Role] = {}
    lead = (
        occurrence.actual_coach_id
        or occurrence.substitute_coach_id
        or occurrence.scheduled_coach_id
    )
    if lead:
        staff[lead] = "lead"
    for uid in occurrence.assistant_coach_ids:
        staff.setdefault(uid, "assistant")
    return staff


def _schedule_moved(before: Session, after: Session) -> bool:
    if any(getattr(before, f) != getattr(after, f) for f in _SCHEDULE_FIELDS):
        return True
    # A one-off class has no recurrence; its instants are its schedule.
    if not after.days_of_week:
        return (before.start_at, before.end_at) != (after.start_at, after.end_at)
    return False


class CoachScheduleNotices:
    """Emits one outbox event per coach whose schedule an admin write changed."""

    def __init__(self, db: Any, outbox: Any) -> None:
        self._sessions = MongoSessionRepository(db)
        self._occurrences = MongoSessionOccurrenceRepository(db)
        self._outbox = outbox

    async def session_snapshot(self, session_id: str) -> Session | None:
        try:
            return await self._sessions.get(session_id)
        except Exception:
            log.warning("coach_schedule_notice_snapshot_failed", exc_info=True)
            return None

    async def occurrence_snapshot(self, occurrence_id: str) -> SessionOccurrence | None:
        try:
            return await self._occurrences.get(occurrence_id)
        except Exception:
            log.warning("coach_schedule_notice_snapshot_failed", exc_info=True)
            return None

    async def session_changed(
        self, before: Session | None, after: Session | None, *, actor_id: str | None
    ) -> None:
        if before is None or after is None:
            return
        old, new = session_staff(before), session_staff(after)
        for uid, role in new.items():
            if old.get(uid) != role:
                await self._emit("assigned", uid, after.session_id, role=role, actor_id=actor_id)
        for uid in old.keys() - new.keys():
            await self._emit("unassigned", uid, after.session_id, actor_id=actor_id)
        if _schedule_moved(before, after):
            for uid in old.keys() & new.keys():
                if old[uid] == new[uid]:
                    await self._emit("moved", uid, after.session_id, actor_id=actor_id)

    async def occurrence_changed(
        self, occurrence_id: str, before: dict[str, Role], *, actor_id: str | None
    ) -> None:
        """Call after a per-date override; ``before`` is who taught it ahead of it."""
        after = await self.occurrence_snapshot(occurrence_id)
        if after is None or after.status == "cancelled":
            return
        new = occurrence_staff(after)
        session_id = after.template_session_id or after.session_id
        for uid in new.keys() - before.keys():
            await self._emit(
                "date_assigned", uid, session_id, occurrence=after, role=new[uid], actor_id=actor_id
            )
        for uid in before.keys() - new.keys():
            await self._emit(
                "date_unassigned", uid, session_id, occurrence=after, actor_id=actor_id
            )

    async def occurrence_cancelled(
        self, before: SessionOccurrence | None, *, reason: str | None, actor_id: str | None
    ) -> None:
        if before is None or before.status == "cancelled":
            return
        session_id = before.template_session_id or before.session_id
        for uid in occurrence_staff(before):
            await self._emit(
                "cancelled",
                uid,
                session_id,
                occurrence=before,
                reason=reason,
                actor_id=actor_id,
                # One cancellation notice per coach per date, even if the
                # route is retried: the outbox converges on a repeated id.
                event_id=f"csn-cancelled-{before.occurrence_id}-{uid}",
            )

    async def _emit(
        self,
        kind: CoachScheduleNoticeKind,
        coach_id: str,
        session_id: str,
        *,
        occurrence: SessionOccurrence | None = None,
        role: Role | None = None,
        reason: str | None = None,
        actor_id: str | None,
        event_id: str | None = None,
    ) -> None:
        if not coach_id or coach_id == actor_id:
            return  # never tell someone about their own change
        try:
            fields: dict[str, Any] = {} if event_id is None else {"event_id": event_id}
            event = CoachScheduleNoticeRequested(
                **fields,
                aggregate_id=session_id,
                academy_id=current_academy_id(),
                payload=CoachScheduleNoticePayload(
                    kind=kind,
                    coach_id=coach_id,
                    session_id=session_id,
                    occurrence_id=occurrence.occurrence_id if occurrence else None,
                    start_at=occurrence.start_at if occurrence else None,
                    role=role,
                    reason=reason[:300] if reason else None,
                    actor_id=actor_id,
                ),
            )
            await self._outbox.append(event)
        except Exception:
            log.warning(
                "coach_schedule_notice_emit_failed",
                extra={"kind": kind, "session_id": session_id},
                exc_info=True,
            )


def _role_words(role: str | None) -> str:
    return "assistant coach" if role == "assistant" else "coach"


def render_notice(
    payload: CoachScheduleNoticePayload,
    *,
    session: Session,
    academy_timezone: str | None,
) -> str:
    title = session.title
    where = f" at {session.location}" if session.location else ""
    schedule = format_session_schedule(session, academy_timezone=academy_timezone)
    when = (
        format_occurrence_when(
            payload.start_at, session_timezone=session.timezone, academy_timezone=academy_timezone
        )
        if payload.start_at
        else schedule
    )
    kind = payload.kind
    if kind == "assigned":
        return f"You are now the {_role_words(payload.role)} for {title}: {schedule}{where}."
    if kind == "unassigned":
        return f"You are no longer coaching {title} ({schedule})."
    if kind == "date_assigned":
        return f"You are coaching {title} on {when}{where}."
    if kind == "date_unassigned":
        return f"You are no longer coaching {title} on {when}."
    if kind == "cancelled":
        reason = f" Reason: {payload.reason}" if payload.reason else ""
        return f"{title} on {when} is cancelled.{reason}"
    return f"{title} has a new time or court: {schedule}{where}."


class CoachScheduleNoticeDelivery:
    """Turns one notice event into one inbox message plus a phone nudge."""

    def __init__(self, db: Any, message_push: Any | None = None) -> None:
        self._sessions = MongoSessionRepository(db)
        self._academies = MongoAcademyRepository(db)
        self._messages = MongoMessageRepository(db)
        self._push = message_push

    async def deliver(self, event: CoachScheduleNoticeRequested) -> Message | None:
        payload = event.payload
        message_id = f"csn-{event.event_id}"
        if await self._messages.get(message_id) is not None:
            return None  # replay of a delivered event
        session = await self._sessions.get(payload.session_id)
        if session is None:
            log.warning("coach_schedule_notice_session_missing", extra={"event_id": event.event_id})
            return None
        academy = await self._academies.find_by_id(current_academy_id()) or {}
        message = Message(
            message_id=message_id,
            academy_id=current_academy_id(),
            kind="dm",
            sender_id=payload.actor_id or "academy",
            sender_persona="admin",
            recipient_id=payload.coach_id,
            body=render_notice(
                payload,
                session=session,
                academy_timezone=str(academy.get("timezone") or "") or None,
            ),
            created_at=datetime.now(UTC),
            author_display_name=str(academy.get("display_name") or academy.get("name") or "")
            or None,
        )
        await self._messages.insert(message)
        if self._push is not None:
            try:
                await self._push.direct_message(message)
            except Exception:
                log.warning("coach_schedule_notice_push_failed", exc_info=True)
        return message


_delivery: CoachScheduleNoticeDelivery | None = None


def install_coach_schedule_delivery(delivery: CoachScheduleNoticeDelivery | None) -> None:
    global _delivery
    _delivery = delivery


@handler(event=CoachScheduleNoticeRequested, schema_version=1)  # type: ignore[arg-type]
async def on_coach_schedule_notice(event: CoachScheduleNoticeRequested) -> None:
    if _delivery is None:
        log.warning("coach_schedule_notice_skipped_no_delivery")
        return
    with tenant_scope(event.academy_id):
        await _delivery.deliver(event)


def compose_coach_schedule_notices(
    db: Any, outbox: Any, *, message_push: Any | None = None
) -> CoachScheduleNotices:
    """Installs the handler's delivery and returns the emitter for app.state."""
    install_coach_schedule_delivery(CoachScheduleNoticeDelivery(db, message_push))
    return CoachScheduleNotices(db, outbox)
