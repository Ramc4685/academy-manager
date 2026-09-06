"""Admin write use cases for Enrollment — sessions + roster + waitlist.

CreateSession, EditSession, CancelSession, EditRoster, TransferEnrollment,
PauseEnrollment, ResumeEnrollment, AdminPromoteFromWaitlist, JoinWaitlist,
SkipWaitlist, RemoveFromWaitlist.

Each emits the right domain event so downstream handlers (waitlist
promotion on cancellation, comms notifications, etc.) react.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, NoReturn, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentBillingSync,
    EnrollmentEventRepository,
    EnrollmentLifecycleBillingPort,
    EnrollmentQuery,
    EnrollmentWelcomeNotifier,
    EnrollmentWriter,
    OccurrenceRosterCleanup,
    RosterChangeKind,
    RosterChangeNotifier,
    SessionWriter,
    StudentQuery,
    StudentWriter,
    WaitlistRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferral,
    BillingDeferralRepository,
    paused_billing_periods,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.errors import (
    # Explicitly re-exported: the interface layer raises 422 on this but may not
    # import domain modules directly (import-linter rule 4).
    AcademyTimezoneUnset as AcademyTimezoneUnset,
)
from backend.v2.contexts.enrollment.domain.errors import (
    CapacityExceeded,
    DuplicateSessionSeries,
    EnrollmentNotFound,
    SeatCounterDrift,
    SessionNotEnrollable,
    SessionNotFound,
    StudentAlreadyOnRoster,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentCancelled,
    EnrollmentCancelledPayload,
    EnrollmentLifecycleEvent,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.security.external_url import validate_external_url

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


async def _record_lifecycle_event(
    enrollment_events: EnrollmentEventRepository | None,
    *,
    academy_id: str,
    event_type: str,
    student_id: str,
    effective_at: datetime,
    occurred_at: datetime,
    enrollment_id: str | None = None,
    waitlist_id: str | None = None,
    session_id: str | None = None,
    from_session_id: str | None = None,
    to_session_id: str | None = None,
    actor_id: str | None = None,
    reason: str | None = None,
    billing_policy: str | None = None,
    billing_result: str | None = None,
    credit_id: str | None = None,
    refund_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    if enrollment_events is None:
        return
    await enrollment_events.record(
        EnrollmentLifecycleEvent(
            event_id=str(new_ulid()),
            academy_id=academy_id,
            event_type=event_type,
            enrollment_id=enrollment_id,
            waitlist_id=waitlist_id,
            session_id=session_id,
            from_session_id=from_session_id,
            to_session_id=to_session_id,
            student_id=student_id,
            actor_id=actor_id,
            reason=reason,
            effective_at=effective_at,
            occurred_at=occurred_at,
            billing_policy=billing_policy,
            billing_result=billing_result,
            credit_id=credit_id,
            refund_id=refund_id,
            metadata=metadata or {},
        )
    )


# -- Session writes ------------------------------------------------------

_DOW_MAP = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _has_recurring_schedule(cmd: CreateSessionCommand) -> bool:
    return bool(cmd.days_of_week and cmd.start_time and cmd.end_time)


def _has_recurring_mapping(values: dict[str, object]) -> bool:
    return bool(values.get("days_of_week") and values.get("start_time") and values.get("end_time"))


def _normalize_series_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _normalize_assistant_ids(values: list[str]) -> tuple[str, ...]:
    """Trim, drop blanks, dedupe preserving order (tuple: the domain field)."""
    seen: dict[str, None] = {}
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return tuple(seen)


def _normalize_days(days_of_week: list[str]) -> list[str]:
    reverse_dow = {
        0: "Mon",
        1: "Tue",
        2: "Wed",
        3: "Thu",
        4: "Fri",
        5: "Sat",
        6: "Sun",
    }
    return [reverse_dow[_DOW_MAP[day]] for day in days_of_week if day in _DOW_MAP]


AcademyTimezoneReader = Callable[[str], Awaitable[str | None]]

_TIMEZONE_UNSET_MESSAGE = (
    "This academy has no timezone set, so session times cannot be interpreted. "
    "Set your academy's timezone in Settings -> Academy before creating sessions."
)


async def _resolve_session_timezone(
    explicit: str | None,
    *,
    academy_id: str,
    reader: AcademyTimezoneReader,
) -> str:
    """The zone a session's wall-clock times are interpreted in.

    Precedence is explicit-on-the-command -> the tenant's own
    ``academies.timezone``. There is deliberately no third rung: a hardcoded
    default is only ever right for one tenant, and being silently wrong here is
    what showed a 6:00 PM class as 1:00 PM on the parent's payment screen.
    """
    chosen = (explicit or "").strip()
    if not chosen:
        chosen = (await reader(academy_id) or "").strip()
    if not chosen:
        raise AcademyTimezoneUnset(_TIMEZONE_UNSET_MESSAGE)
    try:
        ZoneInfo(chosen)
    except (KeyError, ValueError, ZoneInfoNotFoundError) as exc:
        raise AcademyTimezoneUnset(f"'{chosen}' is not a known IANA timezone name.") from exc
    return chosen


def _duplicate_series_message(existing: Session) -> str:
    return (
        "A recurring session already exists for this coach, class, location, "
        f"day, and time: {existing.title}."
    )


def _representative_series_datetimes(
    *,
    days_of_week: list[str],
    start_time: str,
    end_time: str,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    target_days = [_DOW_MAP[day] for day in days_of_week if day in _DOW_MAP]
    if not target_days:
        raise ValueError("days_of_week must include a supported weekday")
    local_date = datetime.now(UTC).astimezone(tz).date()
    while local_date.weekday() not in target_days:
        local_date += timedelta(days=1)
    start = datetime.combine(local_date, time.fromisoformat(start_time), tzinfo=tz)
    end = datetime.combine(local_date, time.fromisoformat(end_time), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


#: The per-session "communication pack" (#613). Named once so the create
#: command, the edit command and the edit update loop cannot drift apart —
#: this feature's whole failure mode is a field silently missing from one hop.
COMMUNICATION_PACK_FIELDS: tuple[str, ...] = (
    "whatsapp_group_link",
    "venue_address",
    "parking_notes",
    "what_to_bring",
    "arrival_minutes_before",
    "coach_contact_policy",
    "absence_policy",
)


async def _notify_roster_change(
    notifier: RosterChangeNotifier | None,
    *,
    change: RosterChangeKind,
    session_id: str,
    student_id: str,
    **details: object,
) -> None:
    """Fire a staff roster alert (#612) without ever risking the write.

    Every caller invokes this as the *last* statement of `execute`, after the
    state has settled: `CancelEnrollment` records its lifecycle event before
    `release_seat`, and the alert quotes a roster count, so firing earlier
    would announce a number that is about to change.

    Swallows everything. A notification failure that propagated would report a
    cancellation as failed to an admin whose cancellation actually happened —
    and the retry would then be a no-op against an already-cancelled row.
    """
    if notifier is None:
        return
    try:
        await notifier.roster_changed(
            change=change,
            session_id=session_id,
            student_id=student_id,
            **details,  # type: ignore[arg-type]
        )
    except Exception:
        log.exception(
            "enrollment.roster_notification_failed",
            extra={"change": change, "session_id": session_id, "student_id": student_id},
        )


async def _drop_future_occurrence_roster(
    cleanup: OccurrenceRosterCleanup | None,
    *,
    session_id: str,
    student_id: str,
    after: datetime,
) -> None:
    """Remove the student's future make-up/trial roster rows (issue #651).

    INVARIANT — every transition that stops attendance in a session (cancel,
    withdraw, session cancelled) calls this after the status write, so a
    coach's day sheet never lists a student whose enrollment is gone. Never
    raises: the enrollment write has already committed and a stale one-time
    row is recoverable, a cancel reported as failed is not.
    """
    if cleanup is None:
        return
    try:
        await cleanup.remove_future_for_student(
            session_id=session_id, student_id=student_id, after=after
        )
    except Exception:
        log.exception(
            "enrollment.occurrence_roster_cleanup_failed",
            extra={"session_id": session_id, "student_id": student_id},
        )


class CreateSessionCommand(BaseModel):
    model_config = {"frozen": True}
    coach_id: str
    title: str
    location: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    capacity: int = Field(ge=1)
    amount_cents: int | None = Field(default=None, ge=0)
    days_of_week: list[str] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    assistant_coach_ids: list[str] = Field(default_factory=list)
    whatsapp_group_link: str | None = None
    venue_address: str | None = None
    parking_notes: str | None = None
    what_to_bring: str | None = None
    arrival_minutes_before: int | None = Field(default=None, ge=0, le=120)
    coach_contact_policy: str | None = None
    absence_policy: str | None = None


class CreateSession:
    def __init__(
        self,
        *,
        sessions: SessionWriter,
        academy_id: str,
        get_academy_timezone: AcademyTimezoneReader,
    ) -> None:
        self._sessions = sessions
        self._academy_id = academy_id
        self._get_academy_timezone = get_academy_timezone

    async def execute(self, cmd: CreateSessionCommand) -> Session:
        start_at = cmd.start_at
        end_at = cmd.end_at
        # Resolve ONCE: the duplicate check, the instant arithmetic and the
        # persisted field must all agree on the same zone.
        timezone_name = await _resolve_session_timezone(
            cmd.timezone,
            academy_id=self._academy_id,
            reader=self._get_academy_timezone,
        )
        if _has_recurring_schedule(cmd):
            await self._ensure_no_duplicate_series(
                title=cmd.title,
                location=cmd.location,
                coach_id=cmd.coach_id,
                days_of_week=cmd.days_of_week,
                start_time=cmd.start_time or "00:00",
                end_time=cmd.end_time or cmd.start_time or "00:00",
                timezone=timezone_name,
            )
        if (start_at is None or end_at is None) and _has_recurring_schedule(cmd):
            start_at, end_at = _representative_series_datetimes(
                days_of_week=cmd.days_of_week,
                start_time=cmd.start_time or "00:00",
                end_time=cmd.end_time or cmd.start_time or "00:00",
                timezone_name=timezone_name,
            )
        if start_at is None or end_at is None:
            raise ValueError("start_at/end_at or recurring schedule fields are required")
        session = Session(
            session_id=str(new_ulid()),
            academy_id=self._academy_id,
            coach_id=cmd.coach_id,
            title=cmd.title,
            location=cmd.location,
            start_at=start_at,
            end_at=end_at,
            capacity=cmd.capacity,
            amount_cents=cmd.amount_cents,
            status="scheduled",
            days_of_week=cmd.days_of_week,
            start_time=cmd.start_time,
            end_time=cmd.end_time,
            assistant_coach_ids=_normalize_assistant_ids(cmd.assistant_coach_ids),
            # Persist the EFFECTIVE zone, never None. `start_at`/`end_at` above
            # were already computed with this zone, and every downstream reader
            # (occurrence synthesis, monthly billing, payroll) re-derives
            # occurrences from `timezone` — leaving it null makes the document
            # depend on each reader's own default agreeing forever.
            timezone=timezone_name,
            **{field: getattr(cmd, field) for field in COMMUNICATION_PACK_FIELDS},
        )
        await self._sessions.create(session)
        return session

    async def _ensure_no_duplicate_series(
        self,
        *,
        title: str,
        location: str,
        coach_id: str,
        days_of_week: list[str],
        start_time: str,
        end_time: str,
        timezone: str,
    ) -> None:
        existing = await self._sessions.find_duplicate_recurring_series(
            title=_normalize_series_text(title),
            location=_normalize_series_text(location),
            coach_id=coach_id,
            days_of_week=_normalize_days(days_of_week),
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
        )
        if existing is not None:
            raise DuplicateSessionSeries(_duplicate_series_message(existing))


class EditSessionCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str
    coach_id: str | None = None
    title: str | None = None
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1)
    amount_cents: int | None = Field(default=None, ge=0)
    days_of_week: list[str] | None = None
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    whatsapp_group_link: str | None = None
    venue_address: str | None = None
    parking_notes: str | None = None
    what_to_bring: str | None = None
    arrival_minutes_before: int | None = Field(default=None, ge=0, le=120)
    coach_contact_policy: str | None = None
    absence_policy: str | None = None
    # None = unchanged, [] = clear (same convention as the PATCH body).
    assistant_coach_ids: list[str] | None = None
    actor_id: str | None = None
    reason: str | None = None


#: Fields an explicit `null` is allowed to clear (see the update loop below).
_CLEARABLE_SESSION_FIELDS: frozenset[str] = frozenset({"amount_cents", *COMMUNICATION_PACK_FIELDS})


class EditSession:
    def __init__(
        self,
        *,
        sessions: SessionWriter,
        get_academy_timezone: AcademyTimezoneReader,
    ) -> None:
        self._sessions = sessions
        self._get_academy_timezone = get_academy_timezone

    async def execute(self, cmd: EditSessionCommand) -> Session:
        current = await self._sessions.get(cmd.session_id)
        if current is None:
            raise SessionNotFound("session missing", session_id=cmd.session_id)

        update: dict[str, object | None] = {}
        for field_name in (
            "coach_id",
            "title",
            "location",
            "start_at",
            "end_at",
            "capacity",
            "amount_cents",
            "days_of_week",
            "start_time",
            "end_time",
            "timezone",
            *COMMUNICATION_PACK_FIELDS,
        ):
            value = getattr(cmd, field_name)
            # An explicit `null` has to be writable for every *optional* field
            # or an admin can set a WhatsApp link and never remove one. The
            # route builds the command with `exclude_unset=True`, so only a
            # body that actually names the field can clear it — a partial
            # PATCH still cannot blank the pack by omission.
            if value is not None or (
                field_name in _CLEARABLE_SESSION_FIELDS and field_name in cmd.model_fields_set
            ):
                update[field_name] = value

        # `model_copy(update=...)` below deliberately skips validators, so the
        # domain field_validator that guards the link on *construction* never
        # runs on an edit. Re-assert it here or the one code path an admin
        # actually uses would be the one path with no scheme check.
        if "whatsapp_group_link" in update:
            update["whatsapp_group_link"] = validate_external_url(
                update["whatsapp_group_link"],  # type: ignore[arg-type]
                field_label="WhatsApp group link",
            )
        # Same skipped-validator caveat: the domain field is a tuple, and the
        # occurrence re-sync for this list is the route's job
        # (`maintain_session_occurrences` re-stamps clean future rows).
        if cmd.assistant_coach_ids is not None:
            update["assistant_coach_ids"] = _normalize_assistant_ids(cmd.assistant_coach_ids)

        recurring_values = {
            "days_of_week": update.get("days_of_week", current.days_of_week),
            "start_time": update.get("start_time", current.start_time),
            "end_time": update.get("end_time", current.end_time),
            "timezone": update.get("timezone", current.timezone),
        }
        title = str(update.get("title", current.title))
        location = str(update.get("location", current.location))
        coach_id = str(update.get("coach_id", current.coach_id))
        if _has_recurring_mapping(recurring_values) and {
            "days_of_week",
            "start_time",
            "end_time",
            "timezone",
            "title",
            "location",
            "coach_id",
        }.intersection(update):
            timezone_name = await _resolve_session_timezone(
                recurring_values["timezone"],  # type: ignore[arg-type]
                academy_id=current.academy_id,
                reader=self._get_academy_timezone,
            )
            existing = await self._sessions.find_duplicate_recurring_series(
                title=_normalize_series_text(title),
                location=_normalize_series_text(location),
                coach_id=coach_id,
                days_of_week=_normalize_days(list(recurring_values["days_of_week"] or [])),
                start_time=str(recurring_values["start_time"] or "00:00"),
                end_time=str(
                    recurring_values["end_time"] or recurring_values["start_time"] or "00:00"
                ),
                timezone=timezone_name,
                exclude_session_id=current.session_id,
            )
            if existing is not None:
                raise DuplicateSessionSeries(_duplicate_series_message(existing))
            start_at, end_at = _representative_series_datetimes(
                days_of_week=list(recurring_values["days_of_week"] or []),
                start_time=str(recurring_values["start_time"] or "00:00"),
                end_time=str(
                    recurring_values["end_time"] or recurring_values["start_time"] or "00:00"
                ),
                timezone_name=timezone_name,
            )
            update["start_at"] = start_at
            update["end_at"] = end_at
            # Write the resolved zone back too. Recomputing instants with a
            # resolved zone while leaving the field null is the split that let
            # a legacy row keep lying to every downstream reader.
            update["timezone"] = timezone_name

        updated = current.model_copy(update=update)
        await self._sessions.update(updated)
        return updated


class CancelSessionCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str


class CancelSession:
    """Cancels a session + emits EnrollmentCancelled for each active or
    paused enrollment.

    The waitlist-promotion handler reacts per cancellation. For session-wide
    cancellation we keep this simple — admin gets a confirmation modal in
    the UI before triggering this.

    Issue #651: paused rows are cancelled too. They already released their
    seat when they paused, so no ``release_seat`` for them — but their open
    billing deferrals are closed and any pending scheduled resume is
    cancelled, otherwise the resume would later reserve a seat in a class
    that no longer runs.
    """

    #: Rows a cancelled class must sweep up (issue #651).
    _CANCELLABLE_STATUSES = ("active", "paused")

    def __init__(
        self,
        *,
        sessions: SessionWriter,
        enrollments_query: EnrollmentQuery,
        enrollments_writer: EnrollmentWriter,
        outbox: Outbox,
        academy_id: str,
        enrollment_events: EnrollmentEventRepository | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        billing_deferrals: BillingDeferralRepository | None = None,
        scheduled_actions: ScheduledEnrollmentActionRepository | None = None,
        occurrence_roster: OccurrenceRosterCleanup | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._enrollments_q = enrollments_query
        self._enrollments_w = enrollments_writer
        self._outbox = outbox
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._roster_notifier = roster_notifier
        self._billing_sync = billing_sync
        self._billing_deferrals = billing_deferrals
        self._scheduled_actions = scheduled_actions
        self._occurrence_roster = occurrence_roster
        self._now = clock

    async def execute(self, cmd: CancelSessionCommand) -> Session | None:
        """Cancel the session and return the post-cancel aggregate.

        The interface layer feeds the returned session back into
        ``maintain_session_occurrences`` (exactly as create/edit do) so the
        already-materialised ``session_occurrences`` rows follow the parent
        into "cancelled" (#467). Returning the aggregate keeps the occurrence
        write in the composition layer that owns that collection instead of
        adding a second occurrence writer here.
        """
        rows = await self._enrollments_q.for_session_in_statuses(
            cmd.session_id, list(self._CANCELLABLE_STATUSES)
        )
        await self._sessions.update_status(cmd.session_id, "cancelled")
        now = self._now()
        for e in rows:
            was_paused = e.status == "paused"
            await self._enrollments_w.update_status(e.enrollment_id, "cancelled")
            await _persist_lifecycle_dates(self._enrollments_w, e.enrollment_id, cancelled_at=now)
            # Issue #651: a cancelled class must release its seats, leave an
            # audit trail per student, and stop billing for every family.
            # A paused row released its seat when it paused; releasing again
            # would drive `reserved_seats` below the truth.
            if not was_paused:
                await self._sessions.release_seat(e.session_id)
            else:
                await self._close_paused_followups(e.enrollment_id, now=now)
            await _drop_future_occurrence_roster(
                self._occurrence_roster,
                session_id=e.session_id,
                student_id=e.student_id,
                after=now,
            )
            billing = await _sync_billing(
                self._billing_sync,
                enrollment_id=e.enrollment_id,
                transition="session_cancelled",
                effective_at=now,
                reason="session_cancelled",
                actor_id=None,
            )
            await _record_lifecycle_event(
                self._enrollment_events,
                academy_id=self._academy_id,
                event_type="cancelled",
                enrollment_id=e.enrollment_id,
                session_id=e.session_id,
                student_id=e.student_id,
                reason="session_cancelled",
                effective_at=now,
                occurred_at=now,
                billing_policy="current_period_payable_future_voided",
                billing_result=_billing_result(billing),
            )
            await _notify_roster_change(
                self._roster_notifier,
                change="session_cancelled",
                session_id=e.session_id,
                student_id=e.student_id,
                enrollment_id=e.enrollment_id,
            )
            await self._outbox.append(
                EnrollmentCancelled(
                    aggregate_id=e.enrollment_id,
                    academy_id=self._academy_id,
                    payload=EnrollmentCancelledPayload(
                        enrollment_id=e.enrollment_id,
                        session_id=cmd.session_id,
                        student_id=e.student_id,
                        reason="session_cancelled",
                    ),
                )
            )
        return await self._sessions.get(cmd.session_id)

    async def _close_paused_followups(self, enrollment_id: str, *, now: datetime) -> None:
        """A paused family's deferral and scheduled resume die with the class
        (issue #651). Best-effort: the cancel has already committed."""
        if self._billing_deferrals is not None:
            try:
                await self._billing_deferrals.close_active_for_enrollment(
                    enrollment_id,
                    closed_at=now,
                    closed_by="system",
                    reason="session_cancelled",
                )
            except Exception:
                log.exception(
                    "enrollment.paused_deferral_close_failed",
                    extra={"enrollment_id": enrollment_id},
                )
        if self._scheduled_actions is not None:
            try:
                await self._scheduled_actions.cancel_pending_for_enrollment(
                    enrollment_id, reason="session_cancelled"
                )
            except Exception:
                log.exception(
                    "enrollment.scheduled_resume_cancel_failed",
                    extra={"enrollment_id": enrollment_id},
                )


# -- Roster + enrollment writes -----------------------------------------


class EditRosterAddCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str
    student_id: str
    parent_id: str
    full_name: str
    actor_id: str | None = None
    reason: str | None = None


class EditRosterAdd:
    """Admin manually adds a student to a session, bypassing checkout.

    Useful for academy comp seats / scholarships. Reserves a seat atomically
    via the same try_reserve_seat path used by ConfirmEnrollment.

    Issue #610 — the reserve is all-or-nothing. `try_reserve_seat` increments
    a shared counter *before* the writes that follow it, so the writes up to
    and including `enrollments.create` run inside a compensating block: a
    failure there releases the seat before the error propagates. Everything
    after that row exists (the lifecycle event, the emails) is best-effort and
    must never release the seat — a released seat under a live enrollment is
    the same drift in the opposite direction, and it lets the session admit
    one student past capacity. Without the compensation, a failed add
    permanently
    inflated `reserved_seats`, and because `release_seat` floors at zero the
    drift is one-way and never self-heals — the reported symptom was a session
    whose roster stayed frozen while its seat count climbed until it looked
    full.
    """

    #: Statuses that mean "this student is already on this roster". A cancelled
    #: row must not block a re-add.
    _BLOCKING_STATUSES = frozenset({"active", "paused"})

    #: Mirrors the `$in` predicate in `MongoSessionWriter.try_reserve_seat`.
    _ENROLLABLE_STATUSES = frozenset({"scheduled", "active", "open"})

    def __init__(
        self,
        *,
        sessions: SessionWriter,
        enrollments: EnrollmentWriter,
        students: StudentWriter,
        academy_id: str | Callable[[], str],
        enrollment_events: EnrollmentEventRepository | None = None,
        welcome_notifier: EnrollmentWelcomeNotifier | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        resume: ResumeEnrollment | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._students = students
        # A callable is resolved at execute time so the request tenant wins
        # over the boot-time value (the #532-class trap); a plain string is
        # still accepted for the non-HTTP callers and the test fakes.
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._welcome_notifier = welcome_notifier
        self._roster_notifier = roster_notifier
        self._resume = resume
        self._now = clock

    def _resolve_academy_id(self) -> str:
        return self._academy_id() if callable(self._academy_id) else self._academy_id

    async def execute(self, cmd: EditRosterAddCommand) -> Enrollment:
        academy_id = self._resolve_academy_id()

        # Pre-check BEFORE reserving, so the common duplicate case costs no
        # seat and gets a message naming the student. This is a TOCTOU read,
        # not a lock — there is no unique (session, student) index — so the
        # DuplicateKeyError arm below stays as the correctness backstop.
        existing = await self._enrollments.find_for_session_student(cmd.session_id, cmd.student_id)
        if existing is not None and existing.status == "paused" and self._resume is not None:
            # A paused row is the same enrollment, not a duplicate: re-adding
            # the student means "resume". Delegating keeps one code path for
            # seat reservation, waitlist cleanup, the lifecycle event, the
            # billing deferral and autopay — the add must never create a
            # second row next to a paused one, and it must never dead-end the
            # admin on a row they cannot see (paused rows used to be hidden
            # from the roster read while still blocking this add).
            await self._resume.execute(
                existing.enrollment_id,
                actor_id=cmd.actor_id,
                reason=cmd.reason or "re-added to roster",
            )
            return existing.model_copy(update={"status": "active"})
        if existing is not None and existing.status in self._BLOCKING_STATUSES:
            hint = (
                "Use Resume on the roster instead."
                if existing.status == "paused"
                else "Remove the existing enrollment first."
            )
            raise StudentAlreadyOnRoster(
                f"{cmd.full_name} is already on this roster ({existing.status}). {hint}",
                session_id=cmd.session_id,
                student_id=cmd.student_id,
                enrollment_id=existing.enrollment_id,
                status=existing.status,
            )

        reserved = await self._sessions.try_reserve_seat(cmd.session_id)
        if not reserved:
            await self._raise_reserve_failure(cmd)

        try:
            # Insert-only: this use case owns no fields on a student that
            # already exists, and a full-model write here nulled their
            # profile and login link (#610).
            await self._students.ensure_exists(
                Student(
                    student_id=cmd.student_id,
                    academy_id=academy_id,
                    parent_id=cmd.parent_id,
                    full_name=cmd.full_name,
                )
            )
            enrollment = Enrollment(
                enrollment_id=str(new_ulid()),
                academy_id=academy_id,
                session_id=cmd.session_id,
                student_id=cmd.student_id,
                status="active",
            )
            await self._enrollments.create(enrollment)
        except DuplicateKeyError as exc:
            await self._release_quietly(cmd.session_id)
            raise StudentAlreadyOnRoster(
                f"Could not add {cmd.full_name} — a conflicting record already "
                f"exists for this student. If they are already on the roster, "
                f"remove that enrollment first; otherwise quote student "
                f"{cmd.student_id} to support.",
                session_id=cmd.session_id,
                student_id=cmd.student_id,
            ) from exc
        except BaseException:
            await self._release_quietly(cmd.session_id)
            raise
        await self._record_created_event(cmd, enrollment, academy_id=academy_id)
        await self._notify_welcome(cmd)
        await _notify_roster_change(
            self._roster_notifier,
            change="added",
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            student_name=cmd.full_name,
            enrollment_id=enrollment.enrollment_id,
            actor_id=cmd.actor_id,
            parent_user_id=cmd.parent_id,
        )
        return enrollment

    async def _record_created_event(
        self,
        cmd: EditRosterAddCommand,
        enrollment: Enrollment,
        *,
        academy_id: str,
    ) -> None:
        """Best-effort lifecycle event, outside the compensating block.

        `enrollments.create` is the point of no return: once the row exists,
        releasing the seat would leave capacity-10 sessions with 10 active
        rows and `reserved_seats == 9`, and nothing reconciles that — the next
        add or parent checkout then admits an eleventh student. The audit
        event is a second write that can fail on its own, so it must not be
        able to trigger the compensation. It is logged and swallowed for the
        same reason the welcome email is: the add really did succeed, and a
        reported failure would send the admin into a retry that the duplicate
        guard rejects.
        """
        now = self._now()
        try:
            await _record_lifecycle_event(
                self._enrollment_events,
                academy_id=academy_id,
                event_type="created",
                enrollment_id=enrollment.enrollment_id,
                session_id=cmd.session_id,
                student_id=cmd.student_id,
                actor_id=cmd.actor_id,
                reason=cmd.reason,
                effective_at=now,
                occurred_at=now,
            )
        except Exception:
            log.exception(
                "enrollment.roster_add_lifecycle_event_failed",
                extra={
                    "session_id": cmd.session_id,
                    "student_id": cmd.student_id,
                    "enrollment_id": enrollment.enrollment_id,
                },
            )

    async def _notify_welcome(self, cmd: EditRosterAddCommand) -> None:
        """Best-effort welcome email (#613).

        Deliberately *after* the compensating block and deliberately
        swallowing: the seat is reserved and the roster row exists, so an
        exception here would leave the admin looking at a failure for an add
        that succeeded — and the retry would then trip the duplicate guard.
        A missed email is recoverable by re-sending; a phantom failure is not.
        """
        if self._welcome_notifier is None:
            return
        try:
            await self._welcome_notifier.send_welcome(
                session_id=cmd.session_id,
                student_name=cmd.full_name,
                parent_user_id=cmd.parent_id,
            )
        except Exception:
            log.exception(
                "enrollment.roster_add_welcome_email_failed",
                extra={"session_id": cmd.session_id, "student_id": cmd.student_id},
            )

    async def _release_quietly(self, session_id: str) -> None:
        """Give the seat back without ever masking the error being handled.

        `release_seat` is idempotent at zero (its Mongo predicate refuses to
        decrement below zero), so calling it on every failure path is safe.
        """
        try:
            await self._sessions.release_seat(session_id)
        except Exception:  # pragma: no cover - defensive
            log.exception(
                "enrollment.roster_add_seat_release_failed",
                extra={"session_id": session_id},
            )

    async def _raise_reserve_failure(self, cmd: EditRosterAddCommand) -> NoReturn:
        """Turn a bare `matched_count == 0` into the error that actually fits.

        The atomic reserve returns False for four different reasons and the
        old code called all of them "session full". Never returns.
        """
        session = await self._sessions.get(cmd.session_id)
        if session is None:
            raise SessionNotFound("session not found", session_id=cmd.session_id)
        if session.status not in self._ENROLLABLE_STATUSES:
            raise SessionNotEnrollable(
                f"This session is {session.status} and cannot take new enrollments.",
                session_id=cmd.session_id,
                status=session.status,
            )
        active_count = await self._enrollments.count_active_for_session(cmd.session_id)
        if active_count >= session.capacity:
            raise CapacityExceeded(
                f"This session is full — {active_count} of {session.capacity} seats are taken.",
                session_id=cmd.session_id,
                capacity=session.capacity,
                active_enrollments=active_count,
            )
        # Reserve refused while the roster is under capacity. Report it with
        # the numbers; do NOT reconcile (see SeatCounterDrift).
        raise SeatCounterDrift(
            f"This session's seat count is out of step with its roster "
            f"({active_count} of {session.capacity} seats enrolled, but the "
            f"seat counter reports it full). It may clear on its own if a "
            f"checkout is in progress; otherwise ask support to reconcile "
            f"session {cmd.session_id}.",
            session_id=cmd.session_id,
            capacity=session.capacity,
            active_enrollments=active_count,
        )


async def _sync_billing(
    billing_sync: EnrollmentBillingSync | None,
    *,
    enrollment_id: str,
    transition: str,
    effective_at: datetime,
    reason: str | None,
    actor_id: str | None,
) -> dict[str, object]:
    """Tell billing attendance stopped/resumed (issue #651). Never raises.

    The enrollment write has already committed when this runs; a billing
    failure must not report the cancel/pause as failed. It IS logged at
    error level, and the lifecycle event carries ``billing_result`` so an
    admin can see that billing did not follow.
    """
    if billing_sync is None:
        log.error(
            "enrollment_billing_sync_unwired: %s for enrollment_id=%s reached billing "
            "nowhere — future invoices stay open and autopay keeps charging",
            transition,
            enrollment_id,
        )
        return {"billing_result": "billing_sync_unwired"}
    try:
        return await billing_sync.apply(
            enrollment_id=enrollment_id,
            transition=transition,
            effective_at=effective_at,
            reason=reason or "",
            actor_id=actor_id,
        )
    except Exception:
        log.exception(
            "enrollment_billing_sync_failed",
            extra={"enrollment_id": enrollment_id, "transition": transition},
        )
        return {"billing_result": "billing_sync_failed"}


async def _persist_lifecycle_dates(
    enrollments: EnrollmentWriter, enrollment_id: str, **dates: datetime
) -> None:
    """Stamp cancelled_at / withdrawal_date on the enrollment when the writer
    supports it (the Mongo writer does; test fakes may not)."""
    setter = getattr(enrollments, "set_lifecycle_dates", None)
    if setter is None:
        return
    await setter(enrollment_id, **dates)


def _billing_result(sync: dict[str, object]) -> str | None:
    value = sync.get("billing_result")
    return str(value) if value is not None else None


class CancelEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    event_type: Literal["cancelled", "removed"] = "cancelled"
    reason: str = Field(default="admin_cancel", min_length=1)
    effective_at: datetime | None = None
    actor_id: str | None = None


class CancelEnrollment:
    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        sessions: SessionWriter,
        outbox: Outbox,
        academy_id: str,
        enrollment_events: EnrollmentEventRepository | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        occurrence_roster: OccurrenceRosterCleanup | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._sessions = sessions
        self._outbox = outbox
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._roster_notifier = roster_notifier
        self._billing_sync = billing_sync
        self._occurrence_roster = occurrence_roster
        self._now = clock

    #: Statuses that no longer hold a seat (issue #651): a paused row released
    #: its seat when it paused and a withdrawn row when it withdrew, so a later
    #: cancel must not release it again and drive `reserved_seats` under the
    #: real roster count.
    _SEATLESS_STATUSES = frozenset({"paused", "withdrawn"})

    async def execute(self, cmd: CancelEnrollmentCommand) -> None:
        e = await self._enrollments.get(cmd.enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        if e.status == "cancelled":
            return
        await self._enrollments.update_status(e.enrollment_id, "cancelled")
        now = self._now()
        effective_at = cmd.effective_at or now
        await _persist_lifecycle_dates(
            self._enrollments, e.enrollment_id, cancelled_at=effective_at
        )
        # Issue #651: billing must follow the cancel (void future invoices,
        # disable autopay) BEFORE the lifecycle event records the outcome.
        billing = await _sync_billing(
            self._billing_sync,
            enrollment_id=e.enrollment_id,
            transition="session_cancelled" if cmd.reason == "session_cancelled" else "cancelled",
            effective_at=effective_at,
            reason=cmd.reason,
            actor_id=cmd.actor_id,
        )
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=self._academy_id,
            event_type=cmd.event_type,
            enrollment_id=e.enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=effective_at,
            occurred_at=now,
            billing_policy="current_period_payable_future_voided",
            billing_result=_billing_result(billing),
        )
        if e.status not in self._SEATLESS_STATUSES:
            await self._sessions.release_seat(e.session_id)
        await _drop_future_occurrence_roster(
            self._occurrence_roster,
            session_id=e.session_id,
            student_id=e.student_id,
            after=effective_at,
        )
        cancel_reason: Literal["admin_cancel", "parent_cancel", "session_cancelled"]
        if cmd.reason in {"admin_cancel", "parent_cancel", "session_cancelled"}:
            cancel_reason = cmd.reason  # type: ignore[assignment]
        else:
            cancel_reason = "admin_cancel"
        await self._outbox.append(
            EnrollmentCancelled(
                aggregate_id=e.enrollment_id,
                academy_id=self._academy_id,
                payload=EnrollmentCancelledPayload(
                    enrollment_id=e.enrollment_id,
                    session_id=e.session_id,
                    student_id=e.student_id,
                    reason=cancel_reason,
                ),
            )
        )
        await _notify_roster_change(
            self._roster_notifier,
            change="cancelled",
            session_id=e.session_id,
            student_id=e.student_id,
            enrollment_id=e.enrollment_id,
            actor_id=cmd.actor_id,
        )


class TransferEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    target_session_id: str
    effective_at: datetime | None = None
    actor_id: str | None = None
    reason: str | None = None


class TransferEnrollment:
    """Move an active or paused enrollment to another session.

    The target seat is reserved first; only after the enrollment points at the
    new session do we release the old session seat.
    """

    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        sessions: SessionWriter,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing: EnrollmentLifecycleBillingPort | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._sessions = sessions
        self._enrollment_events = enrollment_events
        self._billing = billing
        self._roster_notifier = roster_notifier
        self._now = clock

    async def execute(self, cmd: TransferEnrollmentCommand) -> Enrollment:
        enrollment = await self._enrollments.get(cmd.enrollment_id)
        if enrollment is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        if enrollment.session_id == cmd.target_session_id:
            return enrollment
        reserved = await self._sessions.try_reserve_seat(cmd.target_session_id)
        if not reserved:
            from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded

            raise CapacityExceeded("target session full", session_id=cmd.target_session_id)
        await self._enrollments.update_session(enrollment.enrollment_id, cmd.target_session_id)
        now = self._now()
        effective_at = cmd.effective_at or now
        billing_decision = {
            "billing_policy": None,
            "billing_result": None,
            "metadata": {},
        }
        if self._billing is not None and cmd.actor_id is not None:
            billing_decision = await self._billing.record_move_proration(
                enrollment=enrollment,
                from_session_id=enrollment.session_id,
                to_session_id=cmd.target_session_id,
                effective_at=effective_at,
                actor_id=cmd.actor_id,
                reason=cmd.reason,
            )
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=enrollment.academy_id,
            event_type="moved",
            enrollment_id=enrollment.enrollment_id,
            session_id=cmd.target_session_id,
            from_session_id=enrollment.session_id,
            to_session_id=cmd.target_session_id,
            student_id=enrollment.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=effective_at,
            occurred_at=now,
            billing_policy=billing_decision.get("billing_policy"),
            billing_result=billing_decision.get("billing_result"),
            metadata=billing_decision.get("metadata", {}),
        )
        await self._sessions.release_seat(enrollment.session_id)
        await _notify_roster_change(
            self._roster_notifier,
            change="moved",
            # `session_id` is the destination — the roster the student is on
            # now — while both sides ride along so the adapter can tell the
            # coach who lost the student as well as the one who gained them.
            session_id=cmd.target_session_id,
            student_id=enrollment.student_id,
            enrollment_id=enrollment.enrollment_id,
            from_session_id=enrollment.session_id,
            to_session_id=cmd.target_session_id,
            actor_id=cmd.actor_id,
        )
        return enrollment.model_copy(update={"session_id": cmd.target_session_id})


class OverrideEnrollmentFeeCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    amount_cents: int | None = Field(default=None, ge=0)
    actor_id: str | None = None
    reason: str | None = None


class OverrideEnrollmentFee:
    def __init__(self, *, enrollments: EnrollmentWriter) -> None:
        self._enrollments = enrollments

    async def execute(self, cmd: OverrideEnrollmentFeeCommand) -> Enrollment:
        enrollment = await self._enrollments.get(cmd.enrollment_id)
        if enrollment is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        await self._enrollments.update_amount_cents(
            enrollment.enrollment_id,
            cmd.amount_cents,
        )
        return enrollment


class PauseEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    effective_at: datetime | None = None
    actor_id: str | None = None
    reason: str | None = None
    resume_on: date | None = None
    review_on: date | None = None
    create_billing_deferral: bool = True
    pause_stripe_collection: bool = True


class EnrollmentAutopayStatusGateway(Protocol):
    """Cross-context port: toggle a single enrollment's app-owned autopay
    status (Slice B). Per-enrollment — pausing one child never affects a
    sibling. Routes through the guarded transition path on
    ``student_billing_enrollments``; returns True if applied, False if the
    transition was rejected or the enrollment could not be resolved (so the
    caller can log an observable warning). Stripe subscriptions no longer back
    autopay pause/resume — this replaces the Stripe-collection pause path.
    """

    async def set_enrollment_status(self, *, enrollment_id: str, status: str) -> bool: ...


class PauseEnrollment:
    """Pause releases the seat, parks the student at the back of the
    waitlist and stops billing. Resume re-reserves a seat (or fails with
    CapacityExceeded) and returns the row to active.

    Issue #651: the released seat is offered to families that were ALREADY
    waiting via the same ``EnrollmentCancelled`` signal a cancel emits. The
    paused student's own waitlist entry is written first with ``joined_at =
    now`` so FIFO promotion (``next_waiting`` orders by ``joined_at``) can
    never hand the seat straight back to the family that just paused; when
    nobody else is waiting the signal is not sent at all.
    """

    def __init__(
        self,
        enrollments: EnrollmentWriter,
        sessions: SessionWriter | None = None,
        students: StudentQuery | None = None,
        waitlist: WaitlistRepository | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing_deferrals: BillingDeferralRepository | None = None,
        autopay_status: EnrollmentAutopayStatusGateway | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        outbox: Outbox | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._sessions = sessions
        self._students = students
        self._waitlist = waitlist
        self._enrollment_events = enrollment_events
        self._billing_deferrals = billing_deferrals
        self._autopay_status = autopay_status
        self._billing_sync = billing_sync
        self._roster_notifier = roster_notifier
        self._outbox = outbox
        self._now = clock

    async def execute(self, cmd: PauseEnrollmentCommand) -> None:
        e = await self._enrollments.get(cmd.enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing")
        if e.status == "paused":
            return
        await self._enrollments.update_status(e.enrollment_id, "paused")
        now = self._now()
        effective_at = cmd.effective_at or now
        parent_id = ""
        if self._students is not None:
            students = await self._students.by_ids([e.student_id])
            if students:
                parent_id = students[0].parent_id
        waitlist_id: str | None = None
        if self._sessions is not None:
            await self._sessions.release_seat(e.session_id)
        someone_else_waiting = False
        if self._waitlist is not None:
            # Issue #651: read the head of the queue BEFORE adding the paused
            # student, so the seat-released signal below only fires when a
            # different family is actually ahead of them.
            head = await self._waitlist.next_waiting(e.session_id)
            someone_else_waiting = head is not None and head.student_id != e.student_id
            existing_waitlist = await self._waitlist.find_waiting_for_session_student(
                e.session_id, e.student_id
            )
            if existing_waitlist is not None:
                waitlist_id = existing_waitlist.waitlist_id
            else:
                entry = WaitlistEntry(
                    waitlist_id=str(new_ulid()),
                    academy_id=e.academy_id,
                    session_id=e.session_id,
                    student_id=e.student_id,
                    parent_id=parent_id,
                    joined_at=now,
                    status="waiting",
                )
                await self._waitlist.add(entry)
                waitlist_id = entry.waitlist_id
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="paused",
            enrollment_id=e.enrollment_id,
            waitlist_id=waitlist_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=effective_at,
            occurred_at=now,
            billing_policy="release_seat_waitlist_stop_billing",
            billing_result="future_billing_stopped",
            metadata={"seat_policy": "released_to_waitlist"},
        )
        if self._billing_deferrals is not None and cmd.create_billing_deferral:
            # Issue #651: one deferral per PAUSED month. The old single row
            # named the resume month, which the generator never matched.
            for billing_period in paused_billing_periods(
                effective_at=effective_at, resume_on=cmd.resume_on, review_on=cmd.review_on
            ):
                await self._billing_deferrals.add(
                    BillingDeferral(
                        deferral_id=str(new_ulid()),
                        enrollment_id=e.enrollment_id,
                        student_id=e.student_id,
                        deferral_type="admin_pause",
                        reason=cmd.reason or "admin pause",
                        source="admin_direct_pause",
                        actor_id=cmd.actor_id,
                        actor_type="admin" if cmd.actor_id else "system",
                        billing_period=billing_period,
                        resume_on=cmd.resume_on,
                        review_on=cmd.review_on,
                        created_at=now,
                        updated_at=now,
                        metadata={"seat_policy": "released_to_waitlist"},
                    )
                )
        if cmd.pause_stripe_collection and self._autopay_status is not None:
            # App-owned autopay (Slice B): pause toggles THIS enrollment's
            # autopay_enrollment_status to paused (per-enrollment — siblings are
            # unaffected). Stripe subscriptions no longer back autopay.
            applied = await self._autopay_status.set_enrollment_status(
                enrollment_id=e.enrollment_id,
                status="paused",
            )
            if not applied:
                log.warning(
                    "autopay not paused for enrollment_id=%s: rejected transition "
                    "or no billing enrollment (MEDIUM/BLOCKING#2 observability)",
                    e.enrollment_id,
                )
        elif cmd.pause_stripe_collection and self._autopay_status is None:
            log.warning(
                "autopay pause skipped: autopay_status gateway unwired for enrollment_id=%s",
                cmd.enrollment_id,
            )
        if cmd.pause_stripe_collection:
            # Issue #651: void unpaid invoices for the paused months and stop
            # their ladders (autopay status is re-applied idempotently).
            await _sync_billing(
                self._billing_sync,
                enrollment_id=e.enrollment_id,
                transition="paused",
                effective_at=effective_at,
                reason=cmd.reason,
                actor_id=cmd.actor_id,
            )
        if self._outbox is not None and self._sessions is not None and someone_else_waiting:
            # Issue #651: the released seat goes to the family that was
            # already waiting. Appended AFTER the paused student's own waitlist
            # entry (joined last) so FIFO promotion cannot pick them. Reason
            # `admin_cancel` is the payload vocabulary for "a seat opened";
            # the only consumer is the waitlist-promotion handler.
            await self._outbox.append(
                EnrollmentCancelled(
                    aggregate_id=e.enrollment_id,
                    academy_id=e.academy_id,
                    payload=EnrollmentCancelledPayload(
                        enrollment_id=e.enrollment_id,
                        session_id=e.session_id,
                        student_id=e.student_id,
                        reason="admin_cancel",
                    ),
                )
            )
        # Issue #651: staff alert last, after every write has settled.
        await _notify_roster_change(
            self._roster_notifier,
            change="paused",
            session_id=e.session_id,
            student_id=e.student_id,
            enrollment_id=e.enrollment_id,
            actor_id=cmd.actor_id,
        )


class WithdrawEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    effective_at: datetime
    outcome: Literal["credit", "refund", "adjustment"] = "credit"
    actor_id: str
    reason: str = Field(min_length=1)


class WithdrawEnrollment:
    """Mid-term withdrawal: records the credit/refund decision, stops
    billing, and — issue #651 — releases the seat and offers it to the
    waitlist exactly as a cancel does. A withdrawn row that still counted
    against ``reserved_seats`` kept a class "full" for the next family.
    """

    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing: EnrollmentLifecycleBillingPort | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        sessions: SessionWriter | None = None,
        outbox: Outbox | None = None,
        occurrence_roster: OccurrenceRosterCleanup | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._enrollment_events = enrollment_events
        self._billing = billing
        self._roster_notifier = roster_notifier
        self._billing_sync = billing_sync
        self._sessions = sessions
        self._outbox = outbox
        self._occurrence_roster = occurrence_roster
        self._now = clock

    async def execute(self, cmd: WithdrawEnrollmentCommand) -> None:
        e = await self._enrollments.get(cmd.enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing")
        if e.status == "withdrawn":
            return
        now = self._now()
        # The audit row must not claim a credit/refund decision was recorded
        # when no decision port is wired (issue #651).
        billing_decision: dict[str, Any] = {
            "billing_policy": f"withdrawal_{cmd.outcome}",
            "billing_result": "decision_not_recorded",
            "metadata": {"outcome": cmd.outcome},
        }
        if self._billing is not None:
            billing_decision = await self._billing.record_withdrawal_decision(
                enrollment=e,
                outcome=cmd.outcome,
                effective_at=cmd.effective_at,
                actor_id=cmd.actor_id,
                reason=cmd.reason,
            )
        await self._enrollments.update_status(e.enrollment_id, "withdrawn")
        await _persist_lifecycle_dates(
            self._enrollments, e.enrollment_id, withdrawal_date=cmd.effective_at
        )
        # Issue #651: a withdrawn student no longer holds a seat. A paused row
        # released its seat when it paused, so only an active row releases.
        if self._sessions is not None and e.status != "paused":
            await self._sessions.release_seat(e.session_id)
        await _drop_future_occurrence_roster(
            self._occurrence_roster,
            session_id=e.session_id,
            student_id=e.student_id,
            after=cmd.effective_at,
        )
        billing = await _sync_billing(
            self._billing_sync,
            enrollment_id=e.enrollment_id,
            transition="withdrawn",
            effective_at=cmd.effective_at,
            reason=cmd.reason,
            actor_id=cmd.actor_id,
        )
        sync_result = _billing_result(billing)
        if self._billing_sync is not None and sync_result is not None:
            billing_decision = {
                **billing_decision,
                "billing_result": f"{billing_decision.get('billing_result')};{sync_result}",
            }
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="withdrawn",
            enrollment_id=e.enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=cmd.effective_at,
            occurred_at=now,
            billing_policy=billing_decision.get("billing_policy"),
            billing_result=billing_decision.get("billing_result"),
            credit_id=billing_decision.get("credit_id"),
            refund_id=billing_decision.get("refund_id"),
            metadata=billing_decision.get("metadata", {"outcome": cmd.outcome}),
        )
        if self._outbox is not None:
            # Issue #651: the same seat-released signal a cancel emits, so the
            # waitlist-promotion handler fills the seat. `admin_cancel` is the
            # payload's vocabulary for an admin-initiated seat release.
            await self._outbox.append(
                EnrollmentCancelled(
                    aggregate_id=e.enrollment_id,
                    academy_id=e.academy_id,
                    payload=EnrollmentCancelledPayload(
                        enrollment_id=e.enrollment_id,
                        session_id=e.session_id,
                        student_id=e.student_id,
                        reason="admin_cancel",
                    ),
                )
            )
        await _notify_roster_change(
            self._roster_notifier,
            change="withdrawn",
            session_id=e.session_id,
            student_id=e.student_id,
            enrollment_id=e.enrollment_id,
            actor_id=cmd.actor_id,
        )


class ResumeEnrollment:
    """Paused -> active. Reserves a seat first (CapacityExceeded when full).

    Issue #651: refuses to resume into a cancelled session with
    ``SessionNotEnrollable`` BEFORE touching the seat counter — the atomic
    reserve would refuse anyway, but reporting that as "session full" sent
    admins hunting a capacity problem that was not there (#610).
    """

    def __init__(
        self,
        enrollments: EnrollmentWriter,
        sessions: SessionWriter | None = None,
        students: StudentQuery | None = None,
        waitlist: WaitlistRepository | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing_deferrals: BillingDeferralRepository | None = None,
        autopay_status: EnrollmentAutopayStatusGateway | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._sessions = sessions
        self._students = students
        self._waitlist = waitlist
        self._enrollment_events = enrollment_events
        self._billing_deferrals = billing_deferrals
        self._autopay_status = autopay_status
        self._billing_sync = billing_sync
        self._roster_notifier = roster_notifier
        self._now = clock

    async def execute(
        self,
        enrollment_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
        close_billing_deferral: bool = True,
        resume_autopay_collection: bool = True,
    ) -> None:
        e = await self._enrollments.get(enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing")
        if e.status != "paused":
            return
        if self._sessions is not None:
            session = await self._sessions.get(e.session_id)
            if session is not None and session.status == "cancelled":
                raise SessionNotEnrollable(
                    f"Session {e.session_id} is cancelled; the enrollment cannot resume.",
                    session_id=e.session_id,
                    status=session.status,
                )
            reserved = await self._sessions.try_reserve_seat(e.session_id)
            if not reserved:
                raise CapacityExceeded("session full", session_id=e.session_id)
        await self._enrollments.update_status(e.enrollment_id, "active")
        if self._waitlist is not None:
            await self._waitlist.remove_waiting_for_session_student(e.session_id, e.student_id)
        now = self._now()
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="resumed",
            enrollment_id=e.enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=actor_id,
            reason=reason,
            effective_at=now,
            occurred_at=now,
        )
        if resume_autopay_collection and self._autopay_status is not None:
            # App-owned autopay (Slice B): resume toggles THIS enrollment's
            # autopay_enrollment_status back to active (per-enrollment). No
            # Stripe subscription to resume collection on any more.
            applied = await self._autopay_status.set_enrollment_status(
                enrollment_id=e.enrollment_id,
                status="active",
            )
            if not applied:
                log.warning(
                    "autopay not resumed for enrollment_id=%s: rejected transition "
                    "or no billing enrollment (MEDIUM/BLOCKING#2 observability)",
                    e.enrollment_id,
                )
        if resume_autopay_collection and self._autopay_status is None:
            # Issue #651: standalone so it is reachable — it was an `elif`
            # behind `if resume_autopay_collection:` and could never fire.
            log.warning(
                "autopay resume skipped: autopay_status gateway unwired for enrollment_id=%s",
                enrollment_id,
            )
        if resume_autopay_collection:
            await _sync_billing(
                self._billing_sync,
                enrollment_id=e.enrollment_id,
                transition="resumed",
                effective_at=now,
                reason=reason,
                actor_id=actor_id,
            )
        if self._billing_deferrals is not None and close_billing_deferral:
            await self._billing_deferrals.close_active_for_enrollment(
                e.enrollment_id,
                closed_at=now,
                closed_by=actor_id or "system",
                reason="resume_succeeded",
            )
        # Issue #651: staff alert + the family's "you're back on the roster"
        # email, last, after every write has settled.
        await _notify_roster_change(
            self._roster_notifier,
            change="resumed",
            session_id=e.session_id,
            student_id=e.student_id,
            enrollment_id=e.enrollment_id,
            actor_id=actor_id,
        )


# -- Waitlist writes ----------------------------------------------------


class JoinWaitlistCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str
    parent_id: str
    student_id: str
    actor_id: str | None = None
    reason: str | None = None


class JoinWaitlist:
    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        academy_id: str,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._waitlist = waitlist
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(self, cmd: JoinWaitlistCommand) -> WaitlistEntry:
        now = self._now()
        entry = WaitlistEntry(
            waitlist_id=str(new_ulid()),
            academy_id=self._academy_id,
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            parent_id=cmd.parent_id,
            joined_at=now,
            status="waiting",
        )
        await self._waitlist.add(entry)
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=self._academy_id,
            event_type="waitlisted",
            waitlist_id=entry.waitlist_id,
            session_id=entry.session_id,
            student_id=entry.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=now,
            occurred_at=now,
        )
        return entry


class SkipFromWaitlist:
    def __init__(self, waitlist: WaitlistRepository) -> None:
        self._waitlist = waitlist

    async def execute(self, waitlist_id: str) -> None:
        await self._waitlist.update_status(waitlist_id, "skipped")


class RemoveFromWaitlist:
    def __init__(self, waitlist: WaitlistRepository) -> None:
        self._waitlist = waitlist

    async def execute(self, waitlist_id: str) -> None:
        await self._waitlist.update_status(waitlist_id, "removed")
