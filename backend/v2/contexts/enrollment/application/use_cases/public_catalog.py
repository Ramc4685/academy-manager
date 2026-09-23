"""The anonymous public class listing (public tenant page, Lane B2).

Enrollment's half of ``GET /api/v2/public/academy``: published programs with
their published classes, in the allow-listed shape the public page may show.
The academy half (name, branding, venue, page switches) is Identity's and is
joined in the ``interfaces/public`` BFF.

What reaches a stranger is decided here, not in the route, so a hidden price
or an exact seat count never leaves the use case:

* only classes whose ``published`` switch is literally on, that are not
  cancelled or completed, and whose dates are not over (the repository's
  :meth:`available_for_public_catalog`, which unlike the parent catalog keeps
  **full** classes, as ``waitlist``);
* the price only when the academy shows prices, with the class's effective
  period (``ClassPublicProfile.effective_price_period``);
* a seat **band** only when the academy shows availability, never capacity
  or enrolled counts;
* the coach per the class's ``coach_display``;
* opaque public ids, never ``session_id`` / ``program_id`` / ``coach_id``.

Archived programs are not listed; their published classes fall into
``ungrouped_classes`` exactly as B1 reads them ("their classes keep the id
and read as ungrouped"). A program with no published class is not listed.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.program_ports import ProgramRepository
from backend.v2.contexts.enrollment.domain.programs import (
    DEFAULT_PRICE_PERIOD,
    AgeBand,
    ClassPublicProfile,
    PricePeriod,
    Program,
)
from backend.v2.contexts.enrollment.domain.public_catalog import (
    SeatBand,
    coach_public_name,
    public_class_id,
    public_program_id,
    seat_band,
)

#: Hard ceiling on listed classes (brief: realistic range 1 to 40).
MAX_PUBLIC_CLASSES = 200

_WEEKDAY_ORDER = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class PublicCatalogSession(BaseModel):
    """One published class as the repository reads it (internal, never serialised).

    Carries internal ids and exact seat numbers so the use case can derive
    the public shape; the route never sees this type.
    """

    model_config = {"frozen": True}

    profile: ClassPublicProfile
    coach_id: str | None = None
    title: str
    location: str | None = None
    venue_address: str | None = None
    days_of_week: tuple[str, ...] = ()
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    #: Local date of a one-off (non-recurring) class; None for a weekly class.
    starts_on: date | None = None
    capacity: int = Field(ge=0)
    occupied_seats: int = Field(ge=0)
    amount_cents: int | None = Field(default=None, ge=0)


class PublicCatalogSessionQuery(Protocol):
    async def available_for_public_catalog(self) -> list[PublicCatalogSession]:
        """Every listable published class of the tenant in scope, full ones included."""


class CoachNameDirectory(Protocol):
    async def display_names(self, coach_ids: list[str]) -> dict[str, str]:
        """``coach_id -> display name`` for coaches who belong to this academy."""


class PublicPrice(BaseModel):
    model_config = {"frozen": True}

    amount_cents: int = Field(ge=0)
    period: PricePeriod


class PublicSeats(BaseModel):
    model_config = {"frozen": True}

    band: SeatBand
    #: Only inside the ``few`` band (3 or fewer left); otherwise None.
    seats_left: int | None = None


class PublicClassView(BaseModel):
    model_config = {"frozen": True}

    public_id: str
    title: str
    description: str | None = None
    level: str | None = None
    age_band: AgeBand | None = None
    days_of_week: tuple[str, ...] = ()
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    starts_on: date | None = None
    location: str | None = None
    venue_address: str | None = None
    coach_name: str | None = None
    #: None when the academy hides prices or the class has no price set.
    price: PublicPrice | None = None
    #: None when the academy hides availability.
    seats: PublicSeats | None = None


class PublicProgramView(BaseModel):
    model_config = {"frozen": True}

    public_id: str
    name: str
    description: str | None = None
    level: str | None = None
    age_band: AgeBand | None = None
    classes: tuple[PublicClassView, ...]


class PublicCatalog(BaseModel):
    model_config = {"frozen": True}

    programs: tuple[PublicProgramView, ...] = ()
    ungrouped_classes: tuple[PublicClassView, ...] = ()


class ListPublicCatalog:
    def __init__(
        self,
        programs: ProgramRepository,
        sessions: PublicCatalogSessionQuery,
        coach_names: CoachNameDirectory,
    ) -> None:
        self._programs = programs
        self._sessions = sessions
        self._coach_names = coach_names

    async def execute(
        self,
        academy_id: str,
        *,
        price_period_default: PricePeriod = DEFAULT_PRICE_PERIOD,
        show_price: bool = True,
        show_availability: bool = True,
    ) -> PublicCatalog:
        rows = [
            row
            for row in await self._sessions.available_for_public_catalog()
            if row.profile.published is True
        ][:MAX_PUBLIC_CLASSES]
        if not rows:
            return PublicCatalog()
        programs = {p.program_id: p for p in await self._programs.list_all()}
        wanted_coaches = sorted(
            {row.coach_id for row in rows if row.coach_id and row.profile.coach_display != "hidden"}
        )
        names = await self._coach_names.display_names(wanted_coaches) if wanted_coaches else {}

        grouped: dict[str, list[PublicClassView]] = {}
        ungrouped: list[tuple[tuple[object, ...], PublicClassView]] = []
        keyed: dict[str, list[tuple[tuple[object, ...], PublicClassView]]] = {}
        for row in rows:
            program = programs.get(row.profile.program_id or "")
            view = _class_view(
                academy_id,
                row,
                program,
                coach_name=names.get(row.coach_id or ""),
                price_period_default=price_period_default,
                show_price=show_price,
                show_availability=show_availability,
            )
            entry = (_class_sort_key(row), view)
            if program is None:
                ungrouped.append(entry)
            else:
                keyed.setdefault(program.program_id, []).append(entry)
        for program_id, entries in keyed.items():
            grouped[program_id] = [view for _, view in sorted(entries, key=_first)]

        ordered_programs = sorted(
            (programs[pid] for pid in grouped),
            key=lambda p: (p.sort_order, p.name.casefold(), p.program_id),
        )
        return PublicCatalog(
            programs=tuple(
                PublicProgramView(
                    public_id=public_program_id(academy_id, program.program_id),
                    name=program.name,
                    description=program.public_description,
                    level=program.level,
                    age_band=program.age_band,
                    classes=tuple(grouped[program.program_id]),
                )
                for program in ordered_programs
            ),
            ungrouped_classes=tuple(view for _, view in sorted(ungrouped, key=_first)),
        )


def _first(entry: tuple[tuple[object, ...], PublicClassView]) -> tuple[object, ...]:
    return entry[0]


def _class_sort_key(row: PublicCatalogSession) -> tuple[object, ...]:
    first_day = min(
        (_WEEKDAY_ORDER.get(d.strip().lower()[:3], 7) for d in row.days_of_week),
        default=7,
    )
    return (
        row.starts_on or date.min,
        first_day,
        row.start_time or "",
        row.title.casefold(),
        row.profile.session_id,
    )


def _class_view(
    academy_id: str,
    row: PublicCatalogSession,
    program: Program | None,
    *,
    coach_name: str | None,
    price_period_default: PricePeriod,
    show_price: bool,
    show_availability: bool,
) -> PublicClassView:
    profile = row.profile
    price: PublicPrice | None = None
    if show_price and row.amount_cents is not None:
        price = PublicPrice(
            amount_cents=row.amount_cents,
            period=profile.effective_price_period(price_period_default),
        )
    seats: PublicSeats | None = None
    if show_availability:
        band, left = seat_band(row.capacity, row.occupied_seats)
        seats = PublicSeats(band=band, seats_left=left)
    return PublicClassView(
        public_id=public_class_id(academy_id, profile.session_id),
        title=row.title,
        description=profile.public_description,
        level=profile.level or (program.level if program else None),
        age_band=profile.age_band or (program.age_band if program else None),
        days_of_week=row.days_of_week,
        start_time=row.start_time,
        end_time=row.end_time,
        timezone=row.timezone,
        starts_on=row.starts_on,
        location=row.location,
        venue_address=row.venue_address,
        coach_name=coach_public_name(coach_name, profile.coach_display),
        price=price,
        seats=seats,
    )
