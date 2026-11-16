"""Self-booked trials from the public page (L9 A6-1).

A family with no account picks one of the next few dates of a published class
and is booked at once: a ``trial_requests`` row created ``approved`` with the
CRM ``contact_id`` instead of a parent user, the chosen
``assigned_occurrence_id`` and a ``guest_slot`` seat number on that date. The
roster, the coach's Came / Didn't come and the cancel-a-date flow then treat it
like any other approved trial.

* :class:`ListBookableTrialDates`: per published class, the scheduled dates
  from ``BOOKABLE_MIN_LEAD`` to ``BOOKABLE_HORIZON`` ahead. A date is open while
  its guests are below ``min(guest cap, free seats)``, where free seats are the
  class capacity minus seat-holding enrollments and one-time (make-up / trial)
  roster entries for that date. The page shows the first
  ``BOOKABLE_DATES_PER_CLASS`` open ones, each under an opaque ``slot_key``
  (:func:`public_slot_key`), never the occurrence id.
* :class:`BookTrialGuest`: books one date. Unique indexes make it safe under
  concurrency: the seat number (two families taking the last seat leave one
  row; the route answers ``409 Public.SlotUnavailable``), one self-booking per
  canonical inbox per class, and ``ACADEMY_DAILY_GUEST_CEILING`` numbered
  claims per academy per UTC day. Only the two-per-academy mailbox limit is a
  count checked first.
* :class:`ListTrialGuests`: the seated guests of one date for the coach roster
  (parent name and player age only).

BILLING SAFETY: like every trial, no billing dependency; trials are free.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    MAX_PUBLIC_CLASSES,
    PublicCatalogSessionQuery,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.public_catalog import (
    public_class_id,
    public_slot_key,
    seats_left,
)
from backend.v2.contexts.enrollment.domain.self_service import GuestBookingRefusal, TrialRequest
from backend.v2.shared.comms.mailbox import canonical_mailbox
from backend.v2.shared.ids import new_ulid

#: A date closer than this cannot be booked (the coach needs notice).
BOOKABLE_MIN_LEAD = timedelta(hours=3)
#: Nor one further out than this.
BOOKABLE_HORIZON = timedelta(days=21)
#: Dates offered per class.
BOOKABLE_DATES_PER_CLASS = 3
#: Guest bookings one academy takes per UTC day before further requests are
#: filed as plain leads (a bot cycling addresses cannot fill every class).
ACADEMY_DAILY_GUEST_CEILING = 10
#: Active guest bookings per canonical inbox across the academy. (Per class it
#: is one, ever: a unique index.)
MAILBOX_BOOKINGS_PER_ACADEMY = 2
#: Who decided a self-booked trial (``decided_by``).
SELF_BOOKED_BY = "public_self_book"


class BookableOccurrenceQuery(Protocol):
    async def list_upcoming_scheduled_between(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[SessionOccurrence]: ...


class OccurrenceSeatCounts(Protocol):
    async def counts_for_occurrences(self, occurrence_ids: list[str]) -> dict[str, int]: ...


class GuestTrialRepository(Protocol):
    async def guest_counts_for_occurrences(self, occurrence_ids: list[str]) -> dict[str, int]: ...

    async def add_guest(
        self, request: TrialRequest, *, max_slot: int, day_ceiling: int
    ) -> TrialRequest | GuestBookingRefusal: ...

    async def count_active_guests(self, mailbox: str, *, now: datetime) -> int: ...

    async def guests_for_occurrence(self, occurrence_id: str) -> list[TrialRequest]: ...


@dataclass(frozen=True)
class BookableTrialDate:
    """Internal: never serialised to the anonymous caller as is."""

    slot_key: str
    occurrence_id: str
    session_id: str
    #: The class's ``public_class_id``.
    class_public_id: str
    title: str
    start_at: datetime
    #: Highest guest seat number this date may take now.
    max_slot: int
    open: bool


class ListBookableTrialDates:
    def __init__(
        self,
        *,
        sessions: PublicCatalogSessionQuery,
        occurrences: BookableOccurrenceQuery,
        roster: OccurrenceSeatCounts,
        trials: GuestTrialRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._occurrences = occurrences
        self._roster = roster
        self._trials = trials
        self._now = clock

    async def execute(
        self, academy_id: str, *, guest_cap: int
    ) -> dict[str, list[BookableTrialDate]]:
        """``class public_id -> the first open dates`` (at most
        ``BOOKABLE_DATES_PER_CLASS``) for every published class with any."""
        shown: dict[str, list[BookableTrialDate]] = {}
        for date in await self._all_dates(academy_id, guest_cap=guest_cap):
            dates = shown.setdefault(date.class_public_id, [])
            if date.open and len(dates) < BOOKABLE_DATES_PER_CLASS:
                dates.append(date)
        return {public_id: dates for public_id, dates in shown.items() if dates}

    async def find(
        self, academy_id: str, slot_key: str, *, guest_cap: int
    ) -> BookableTrialDate | None:
        """The in-window date behind ``slot_key`` (open or not), or None for a
        key that names nothing bookable of this academy."""
        wanted = slot_key.strip()
        if not wanted:
            return None
        for date in await self._all_dates(academy_id, guest_cap=guest_cap):
            if date.slot_key == wanted:
                return date
        return None

    async def _all_dates(self, academy_id: str, *, guest_cap: int) -> list[BookableTrialDate]:
        classes = [
            row
            for row in await self._sessions.available_for_public_catalog()
            if row.profile.published is True
        ][:MAX_PUBLIC_CLASSES]
        if not classes:
            return []
        by_session = {row.profile.session_id: row for row in classes}
        now = self._now()
        occurrences = [
            o
            for o in await self._occurrences.list_upcoming_scheduled_between(
                start_at=now + BOOKABLE_MIN_LEAD, end_at=now + BOOKABLE_HORIZON
            )
            if o.status == "scheduled" and (o.template_session_id or o.session_id) in by_session
        ]
        ids = [o.occurrence_id for o in occurrences]
        roster = await self._roster.counts_for_occurrences(ids) if ids else {}
        guests = await self._trials.guest_counts_for_occurrences(ids) if ids else {}
        dates: list[BookableTrialDate] = []
        for occurrence in sorted(occurrences, key=lambda o: o.start_at):
            row = by_session[occurrence.template_session_id or occurrence.session_id]
            free = seats_left(
                row.capacity, row.occupied_seats + roster.get(occurrence.occurrence_id, 0)
            )
            max_slot = min(guest_cap, free)
            dates.append(
                BookableTrialDate(
                    slot_key=public_slot_key(academy_id, occurrence.occurrence_id),
                    occurrence_id=occurrence.occurrence_id,
                    session_id=row.profile.session_id,
                    class_public_id=public_class_id(academy_id, row.profile.session_id),
                    title=row.title,
                    start_at=occurrence.start_at,
                    max_slot=max_slot,
                    open=guests.get(occurrence.occurrence_id, 0) < max_slot,
                )
            )
        return dates


@dataclass(frozen=True)
class BookTrialGuestCommand:
    academy_id: str
    date: BookableTrialDate
    contact_id: str
    #: The booker's email as typed; the limits use its canonical inbox.
    email: str
    guest_name: str
    guest_age: str | None


@dataclass(frozen=True)
class BookTrialGuestResult:
    booking: TrialRequest | None
    refused: GuestBookingRefusal | None = None


class BookTrialGuest:
    def __init__(
        self,
        *,
        trials: GuestTrialRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._trials = trials
        self._now = clock

    async def execute(self, cmd: BookTrialGuestCommand) -> BookTrialGuestResult:
        now = self._now()
        mailbox = canonical_mailbox(cmd.email) or cmd.email
        # A booking is "active" until its date starts.
        # shortcut: count-then-insert, so two concurrent bookings of different
        # classes by one inbox can both pass the per-academy limit (at most one
        # per class still holds); make it a claim if abuse shows up.
        if await self._trials.count_active_guests(mailbox, now=now) >= (
            MAILBOX_BOOKINGS_PER_ACADEMY
        ):
            return BookTrialGuestResult(booking=None, refused="mailbox_limit")
        if not cmd.date.open:
            return BookTrialGuestResult(booking=None, refused="full")
        day = cmd.date.start_at.date().isoformat()
        request = TrialRequest(
            request_id=str(new_ulid()),
            academy_id=cmd.academy_id,
            contact_id=cmd.contact_id,
            student_ref="prospective",
            requested_session_id=cmd.date.session_id,
            preferred_start=day,
            preferred_end=day,
            status="approved",
            assigned_occurrence_id=cmd.date.occurrence_id,
            decided_by=SELF_BOOKED_BY,
            decided_at=now,
            created_at=now,
            guest_name=cmd.guest_name,
            guest_age=cmd.guest_age,
            guest_mailbox=mailbox,
            guest_starts_at=cmd.date.start_at,
        )
        booked = await self._trials.add_guest(
            request, max_slot=cmd.date.max_slot, day_ceiling=ACADEMY_DAILY_GUEST_CEILING
        )
        if isinstance(booked, str):
            return BookTrialGuestResult(booking=None, refused=booked)
        return BookTrialGuestResult(booking=booked)


class ListTrialGuests:
    """The website guests booked on one class date, for the coach roster."""

    def __init__(self, *, trials: GuestTrialRepository) -> None:
        self._trials = trials

    async def execute(self, occurrence_id: str) -> list[TrialRequest]:
        return await self._trials.guests_for_occurrence(occurrence_id)
