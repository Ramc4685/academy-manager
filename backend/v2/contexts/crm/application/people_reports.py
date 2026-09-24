"""People reports on ``/admin/reports``: money owed by age band and inquiry
conversion by source (roadmap L5a), attendance risk by class and coach and
families lost and why (roadmap L5b).

The L5a cards:

* **Money owed by age band.** Open balance bucketed by days past due (1 to 30,
  31 to 60, over 60) plus what is not yet due, with the family count and total
  per band. No balance arithmetic lives here. Billing's money read model is
  the one rule (``family_money.summarize_family_money``: open statuses only,
  ``balance_due_cents`` as the ledger left it after payments, credits and
  refunds), and it already answers "how much of this family's open balance
  was due before day D". Asking it for D = today, today - 30 and today - 60
  gives each band as a difference of two of its own answers, so the bands add
  up to the family index's ``overdue_cents`` exactly, and "not yet due" plus
  the bands add up to its ``balance_cents``. Families are the family index's
  (same alias map, same academy today), so the report and the Families view
  can never disagree about who owes what.
* **Inquiry to enrolled by source.** ``crm_contacts`` counted by ``source`` and
  ``pipeline_status`` over a created-at window (default: the last 90 days in
  the academy's timezone). Existing fields only.

The L5b cards reuse existing derivations rather than re-implementing them:

* **Attendance risk** groups each seated student's ``derive_lifecycle`` state
  (the ``/admin/students`` answer, whose attendance window and voided-mark
  rule live in the enrollment context) by class and by the class's coach.
* **Families lost** takes the family index's Left families and explains each
  with the structured ``reason_code`` of its departure events (#775), or,
  where none was recorded, by the transition that ended its last class.

Money is gated at the interface by ``can_view_family_money``; the other three
cards carry no money.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from backend.v2.contexts.crm.application.family_index import FamilyIndex
from backend.v2.contexts.crm.application.ports import FamilyMoneyFacts, FamilyMoneyReader
from backend.v2.contexts.crm.domain.models import CONTACT_SOURCES, PIPELINE_STATUSES
from backend.v2.shared.tenancy import tenant_scope

# --------------------------------------------------------------------------
# Money owed by age band
# --------------------------------------------------------------------------

#: ``(key, label, first day past due, last day past due or None)``. A due date
#: exactly 30 days ago is in the first band, 31 in the second, 60 in the
#: second, 61 in the last.
AGE_BANDS: Final[tuple[tuple[str, str, int, int | None], ...]] = (
    ("days_1_30", "1 to 30 days late", 1, 30),
    ("days_31_60", "31 to 60 days late", 31, 60),
    ("days_over_60", "Over 60 days late", 61, None),
)
NOT_YET_DUE_KEY: Final[str] = "not_yet_due"


class PeopleReportUnavailable(RuntimeError):
    """The money source could not be read: the report says so, never a zero."""


@dataclass(frozen=True)
class AgeBandTotal:
    key: str
    label: str
    #: Days past due, inclusive. None for an open end.
    min_days: int | None
    max_days: int | None
    #: Families with money in this band (a family may be in several bands).
    family_count: int
    total_cents: int


@dataclass(frozen=True)
class MoneyOwedByAge:
    as_of: date
    generated_at: datetime
    not_yet_due: AgeBandTotal
    bands: tuple[AgeBandTotal, ...]
    #: Sum of the bands: the family index's overdue total.
    overdue_cents: int
    overdue_family_count: int
    #: ``not_yet_due`` plus the bands: the family index's balance total.
    balance_cents: int
    owing_family_count: int


def _overdue(facts: Mapping[str, FamilyMoneyFacts], family: str) -> int:
    found = facts.get(family)
    return found.overdue_cents if found is not None else 0


def age_family_money(
    *,
    as_of: date,
    generated_at: datetime,
    due_before_today: Mapping[str, FamilyMoneyFacts],
    due_before_day_30: Mapping[str, FamilyMoneyFacts],
    due_before_day_60: Mapping[str, FamilyMoneyFacts],
) -> MoneyOwedByAge:
    """Bands from three money snapshots taken with ``today`` shifted.

    ``due_before_today[f].overdue_cents`` is family ``f``'s open money due
    before today; the ``day_30`` / ``day_60`` snapshots are the same rule with
    today moved back 30 and 60 days. Overdue sets nest (due before today - 60
    is also due before today - 30), so each band is a non-negative difference.
    A band is clamped at zero only to survive an invoice changing between the
    reads; on consistent data the clamp never fires.
    """
    band_cents = [0, 0, 0]
    band_families = [0, 0, 0]
    not_yet_due_cents = 0
    not_yet_due_families = 0
    balance_cents = 0
    overdue_cents = 0
    owing = 0
    overdue_families = 0
    for family, facts in due_before_today.items():
        over_0 = facts.overdue_cents
        over_30 = _overdue(due_before_day_30, family)
        over_60 = _overdue(due_before_day_60, family)
        per_band = (max(over_0 - over_30, 0), max(over_30 - over_60, 0), max(over_60, 0))
        for i, cents in enumerate(per_band):
            band_cents[i] += cents
            if cents > 0:
                band_families[i] += 1
        current = facts.balance_cents - over_0
        not_yet_due_cents += current
        if current > 0:
            not_yet_due_families += 1
        balance_cents += facts.balance_cents
        overdue_cents += sum(per_band)
        if facts.balance_cents > 0:
            owing += 1
        if over_0 > 0:
            overdue_families += 1
    bands = tuple(
        AgeBandTotal(
            key=key,
            label=label,
            min_days=low,
            max_days=high,
            family_count=band_families[i],
            total_cents=band_cents[i],
        )
        for i, (key, label, low, high) in enumerate(AGE_BANDS)
    )
    return MoneyOwedByAge(
        as_of=as_of,
        generated_at=generated_at,
        not_yet_due=AgeBandTotal(
            key=NOT_YET_DUE_KEY,
            label="Not yet due",
            min_days=None,
            max_days=0,
            family_count=not_yet_due_families,
            total_cents=not_yet_due_cents,
        ),
        bands=bands,
        overdue_cents=overdue_cents,
        overdue_family_count=overdue_families,
        balance_cents=balance_cents,
        owing_family_count=owing,
    )


class FamilyIndexSource(Protocol):
    """The family index read model: who the families are, and the academy's today."""

    async def build(self, academy_id: str) -> FamilyIndex: ...

    async def academy_today(self, academy_id: str) -> date: ...


class MoneyOwedByAgeReport:
    """``GET /admin/reports/people/money-owed-by-age``."""

    def __init__(
        self,
        *,
        index: FamilyIndexSource,
        money: FamilyMoneyReader,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._index = index
        self._money = money
        self._clock = clock

    async def run(self, academy_id: str) -> MoneyOwedByAge:
        # FamilyIndexUnavailable (a primary source failed) propagates: 503.
        index = await self._index.build(academy_id)
        today = await self._index.academy_today(academy_id)
        try:
            snapshots = [
                await self._money.summaries(
                    academy_id=academy_id, family_by_alias=index.family_by_alias, today=day
                )
                for day in (today, today - timedelta(days=30), today - timedelta(days=60))
            ]
        except Exception as exc:
            raise PeopleReportUnavailable("money unavailable") from exc
        return age_family_money(
            as_of=today,
            generated_at=self._clock(),
            due_before_today=snapshots[0],
            due_before_day_30=snapshots[1],
            due_before_day_60=snapshots[2],
        )


# --------------------------------------------------------------------------
# Inquiry to enrolled by source
# --------------------------------------------------------------------------

DEFAULT_WINDOW_DAYS: Final[int] = 90
#: Longest window one request may ask for (two years and a day).
MAX_WINDOW_DAYS: Final[int] = 731
#: Display order: the public form first, then the staff sources.
SOURCE_ORDER: Final[tuple[str, ...]] = ("website", "whatsapp_or_phone", "referral", "other")
_UTC_NAME = "UTC"


class InvalidReportRange(ValueError):
    """``from`` after ``to``, or a window longer than :data:`MAX_WINDOW_DAYS`."""


class CrmContactStats(Protocol):
    async def count_by_source_and_status(
        self, *, created_from: datetime, created_before: datetime
    ) -> list[tuple[str, str, int]]:
        """``(source, pipeline_status, count)`` for the current academy's
        contacts created in ``[created_from, created_before)``."""
        ...


@dataclass(frozen=True)
class SourceConversion:
    source: str
    inquiries: int
    lead: int
    trial: int
    enrolled: int
    #: ``enrolled / inquiries``; None when there were no inquiries.
    conversion_rate: float | None


@dataclass(frozen=True)
class InquiryConversion:
    date_from: date
    date_to: date
    timezone: str
    sources: tuple[SourceConversion, ...]
    total: SourceConversion


def _row(source: str, counts: Mapping[str, int]) -> SourceConversion:
    lead = counts.get("lead", 0)
    trial = counts.get("trial", 0)
    enrolled = counts.get("enrolled", 0)
    inquiries = lead + trial + enrolled
    return SourceConversion(
        source=source,
        inquiries=inquiries,
        lead=lead,
        trial=trial,
        enrolled=enrolled,
        conversion_rate=(enrolled / inquiries) if inquiries else None,
    )


def summarize_inquiry_conversion(
    rows: Iterable[tuple[str, str, int]], *, date_from: date, date_to: date, timezone: str
) -> InquiryConversion:
    """Every known source gets a row (zeros included) so the table never
    silently drops one. A stored value outside the vocabularies is counted
    under ``other`` / ``lead`` rather than lost from the total."""
    by_source: dict[str, dict[str, int]] = {source: {} for source in SOURCE_ORDER}
    for source, status, count in rows:
        source_key = source if source in CONTACT_SOURCES else "other"
        status_key = status if status in PIPELINE_STATUSES else "lead"
        bucket = by_source.setdefault(source_key, {})
        bucket[status_key] = bucket.get(status_key, 0) + int(count)
    total_counts = {
        status: sum(bucket.get(status, 0) for bucket in by_source.values())
        for status in ("lead", "trial", "enrolled")
    }
    return InquiryConversion(
        date_from=date_from,
        date_to=date_to,
        timezone=timezone,
        sources=tuple(_row(source, by_source[source]) for source in SOURCE_ORDER),
        total=_row("all", total_counts),
    )


def _zone(name: str | None) -> tuple[ZoneInfo, str]:
    if name:
        try:
            return ZoneInfo(name), name
        except Exception:  # an unknown zone name reads as UTC, visibly
            pass
    return ZoneInfo(_UTC_NAME), _UTC_NAME


def _local_day_window(
    zone: ZoneInfo, today: date, date_from: date | None, date_to: date | None
) -> tuple[date, date, datetime, datetime]:
    """``(start, end, utc_from, utc_before)`` for academy-local days ``from``
    to ``to`` (both inclusive; default the last :data:`DEFAULT_WINDOW_DAYS`
    days ending today). Raises :class:`InvalidReportRange`."""
    end = date_to or today
    start = date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    if start > end:
        raise InvalidReportRange("from must be on or before to")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise InvalidReportRange(f"the window may be at most {MAX_WINDOW_DAYS} days")
    utc_from = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
    utc_before = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return start, end, utc_from, utc_before


class InquiryConversionReport:
    """``GET /admin/reports/people/inquiry-conversion?from=&to=``.

    ``from`` and ``to`` are academy-local calendar days, both inclusive; the
    window is ``[from 00:00, to + 1 day 00:00)`` in the academy's timezone.
    Contacts are read through the tenant-scoped repository with the tenant
    context pinned to ``academy_id``, so only that academy is ever counted.
    """

    def __init__(
        self,
        *,
        contacts: CrmContactStats,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._contacts = contacts
        self._academy_timezone = academy_timezone
        self._clock = clock

    async def run(
        self, academy_id: str, *, date_from: date | None = None, date_to: date | None = None
    ) -> InquiryConversion:
        zone, zone_name = _zone(await self._academy_timezone(academy_id))
        today = self._clock().astimezone(zone).date()
        start, end, created_from, created_before = _local_day_window(
            zone, today, date_from, date_to
        )
        # The contacts port is tenant-scoped (it reads the ContextVar), so pin
        # the ContextVar to the academy this run was asked for: the count then
        # honours the same academy_id as the money report even when the route
        # resolved it from the claims rather than the request context.
        with tenant_scope(academy_id):
            rows = await self._contacts.count_by_source_and_status(
                created_from=created_from, created_before=created_before
            )
        return summarize_inquiry_conversion(rows, date_from=start, date_to=end, timezone=zone_name)


# --------------------------------------------------------------------------
# Attendance risk by class and by coach (roadmap L5b)
# --------------------------------------------------------------------------

#: The child lifecycle state that means "stopped coming". It is the
#: enrollment context's ``derive_lifecycle`` answer (no attendance in the last
#: three scheduled dates of a class the student holds a seat in, voided marks
#: excluded), read through :class:`ChildLifecycleReader`; this report never
#: re-derives it and never opens its own attendance window.
AT_RISK_STATE: Final[str] = "at_risk"
NO_COACH_KEY: Final[str] = ""


@dataclass(frozen=True)
class RiskStudent:
    """One student's lifecycle snapshot, as the enrollment context derived it."""

    student_id: str
    state: str
    live_session_ids: tuple[str, ...]


@dataclass(frozen=True)
class RiskClass:
    """A class the academy runs, with its scheduled coach."""

    session_id: str
    title: str
    coach_id: str | None


@dataclass(frozen=True)
class AttendanceRiskFacts:
    students: tuple[RiskStudent, ...]
    #: Every class a student holds a seat in, keyed by ``session_id``. A seat
    #: in a class that no longer has a document still counts, under its id.
    classes: Mapping[str, RiskClass]
    #: Display names for the coach ids on :attr:`classes` (only ids that are
    #: members of this academy resolve).
    coach_names: Mapping[str, str]


class AttendanceRiskSource(Protocol):
    async def facts(self, academy_id: str) -> AttendanceRiskFacts: ...


@dataclass(frozen=True)
class ClassRiskRow:
    session_id: str
    title: str
    coach_id: str | None
    coach_name: str | None
    #: Students holding a seat in this class.
    students: int
    #: Of those, students whose lifecycle is at_risk.
    at_risk: int
    #: ``at_risk / students``; None when the class has no students.
    at_risk_rate: float | None


@dataclass(frozen=True)
class CoachRiskRow:
    #: None for classes with no scheduled coach.
    coach_id: str | None
    coach_name: str | None
    classes: int
    #: Distinct students across the coach's classes (a student in two of the
    #: coach's classes is one student).
    students: int
    at_risk: int
    at_risk_rate: float | None


@dataclass(frozen=True)
class AttendanceRisk:
    generated_at: datetime
    by_class: tuple[ClassRiskRow, ...]
    by_coach: tuple[CoachRiskRow, ...]
    #: Distinct students holding any seat, and how many of them are at_risk.
    students: int
    at_risk: int


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _risk_order(at_risk: int, rate: float | None, name: str) -> tuple[int, float, str]:
    """Most at-risk students first, then the highest share, then by name."""
    return (-at_risk, -(rate or 0.0), name.lower())


def summarize_attendance_risk(
    facts: AttendanceRiskFacts, *, generated_at: datetime
) -> AttendanceRisk:
    """Group the students' own lifecycle answers by the classes they hold a
    seat in, then by each class's scheduled coach.

    A student is at risk as a person, not per class (the lifecycle rule takes
    the forgiving reading: attending one of their classes clears the flag), so
    an at-risk student in two classes is counted in both classes, and once per
    coach.
    """
    members: dict[str, set[str]] = {}
    at_risk_members: dict[str, set[str]] = {}
    seated: set[str] = set()
    flagged: set[str] = set()
    for student in facts.students:
        if not student.live_session_ids:
            continue
        seated.add(student.student_id)
        risky = student.state == AT_RISK_STATE
        if risky:
            flagged.add(student.student_id)
        for session_id in student.live_session_ids:
            members.setdefault(session_id, set()).add(student.student_id)
            if risky:
                at_risk_members.setdefault(session_id, set()).add(student.student_id)

    class_rows: list[ClassRiskRow] = []
    coach_classes: dict[str, int] = {}
    coach_students: dict[str, set[str]] = {}
    coach_flagged: dict[str, set[str]] = {}
    for session_id, roster in members.items():
        found = facts.classes.get(session_id)
        coach_id = found.coach_id if found is not None and found.coach_id else None
        flagged_here = at_risk_members.get(session_id, set())
        class_rows.append(
            ClassRiskRow(
                session_id=session_id,
                title=(found.title if found is not None and found.title else session_id),
                coach_id=coach_id,
                coach_name=facts.coach_names.get(coach_id) if coach_id else None,
                students=len(roster),
                at_risk=len(flagged_here),
                at_risk_rate=_rate(len(flagged_here), len(roster)),
            )
        )
        key = coach_id or NO_COACH_KEY
        coach_classes[key] = coach_classes.get(key, 0) + 1
        coach_students.setdefault(key, set()).update(roster)
        coach_flagged.setdefault(key, set()).update(flagged_here)

    coach_rows = [
        CoachRiskRow(
            coach_id=key or None,
            coach_name=facts.coach_names.get(key) if key else None,
            classes=coach_classes[key],
            students=len(coach_students[key]),
            at_risk=len(coach_flagged[key]),
            at_risk_rate=_rate(len(coach_flagged[key]), len(coach_students[key])),
        )
        for key in coach_classes
    ]
    class_rows.sort(key=lambda r: (*_risk_order(r.at_risk, r.at_risk_rate, r.title), r.session_id))
    coach_rows.sort(
        key=lambda r: (
            *_risk_order(r.at_risk, r.at_risk_rate, r.coach_name or r.coach_id or "~"),
            r.coach_id or "",
        )
    )
    return AttendanceRisk(
        generated_at=generated_at,
        by_class=tuple(class_rows),
        by_coach=tuple(coach_rows),
        students=len(seated),
        at_risk=len(flagged),
    )


class AttendanceRiskReport:
    """``GET /admin/reports/people/attendance-risk``."""

    def __init__(
        self,
        *,
        source: AttendanceRiskSource,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._source = source
        self._clock = clock

    async def run(self, academy_id: str) -> AttendanceRisk:
        try:
            facts = await self._source.facts(academy_id)
        except Exception as exc:
            raise PeopleReportUnavailable("attendance risk unavailable") from exc
        return summarize_attendance_risk(facts, generated_at=self._clock())


# --------------------------------------------------------------------------
# Families lost and why (roadmap L5b)
# --------------------------------------------------------------------------

#: Why a family left: the structured ``reason_code`` the Drop and
#: Stop-all-classes dialogs record on the departure event (#775). Spelled
#: again here because contexts may not import each other;
#: ``test_crm_people_reports_l5b`` pins it equal to the enrollment context's
#: ``DEPARTURE_REASON_CODES``.
LEAVING_REASON_CODES: Final[tuple[str, ...]] = (
    "moved_away",
    "schedule_conflict",
    "cost",
    "lost_interest",
    "injury_or_health",
    "switched_academy",
    "coaching_fit",
    "season_break",
    "non_payment",
    "other",
)

#: Departure event type -> ``(transition key, label)``: how the family left
#: when nobody recorded why. Keys of this map are exactly the leaving report's
#: ``DEPARTURE_EVENT_TYPES`` (#698, pinned equal by the same test).
DEPARTURE_TRANSITIONS: Final[Mapping[str, tuple[str, str]]] = {
    "withdrawn": ("dropped_by_staff", "Dropped by staff"),
    "dropped": ("dropped_by_staff", "Dropped by staff"),
    "removed": ("removed_by_staff", "Enrollment deleted by staff"),
    "cancelled": ("cancelled_by_family", "Cancelled by the family"),
    "hold_reclaimed": ("hold_reclaimed", "Held seat given to another student"),
    "hold_reclaim_orphaned": ("hold_reclaimed", "Held seat given to another student"),
    "hold_expired": ("hold_expired", "Hold ran out"),
    "deleted": ("class_removed", "Class cancelled or removed"),
}
TRANSITION_ORDER: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(key for key, _label in DEPARTURE_TRANSITIONS.values())
)
_TRANSITION_LABELS: Final[dict[str, str]] = dict(DEPARTURE_TRANSITIONS.values())
_LEFT_STAGE: Final[str] = "left"


@dataclass(frozen=True)
class DepartureFact:
    """One departure event from ``enrollment_events``."""

    student_id: str
    event_type: str
    reason_code: str | None
    effective_at: datetime


class DepartureSource(Protocol):
    async def departures(
        self, academy_id: str, *, effective_from: datetime, effective_before: datetime
    ) -> list[DepartureFact]:
        """This academy's departure events that took effect in
        ``[effective_from, effective_before)``."""
        ...


class LostFamiliesIndexSource(Protocol):
    async def build(self, academy_id: str) -> FamilyIndex: ...


@dataclass(frozen=True)
class ReasonCount:
    key: str
    label: str | None
    families: int


@dataclass(frozen=True)
class FamiliesLost:
    date_from: date
    date_to: date
    timezone: str
    #: Families whose stage is Left today and whose last class ended in the
    #: window.
    families_lost: int
    #: Families with a recorded reason, per reason (every code, zeros kept).
    by_reason: tuple[ReasonCount, ...]
    with_reason: int
    #: Families with no recorded reason, by how their last class ended.
    by_transition: tuple[ReasonCount, ...]
    without_reason: int


def _latest(events: Iterable[DepartureFact]) -> DepartureFact | None:
    return max(events, key=lambda e: e.effective_at, default=None)


def summarize_families_lost(
    index: FamilyIndex,
    departures: Iterable[DepartureFact],
    *,
    date_from: date,
    date_to: date,
    timezone: str,
) -> FamiliesLost:
    """A family is lost when every child has left (its stage today is Left)
    and at least one child's departure took effect in the window. Its reason
    is the latest recorded ``reason_code`` among those departures; with none
    recorded, the family is counted by how its latest departure happened.
    A family that left and came back is not lost."""
    family_of_student = {
        child.student_id: record.family_id
        for record in index.families
        if record.stage == _LEFT_STAGE
        for child in record.children
    }
    by_family: dict[str, list[DepartureFact]] = {}
    for event in departures:
        family = family_of_student.get(event.student_id)
        if family is not None and event.event_type in DEPARTURE_TRANSITIONS:
            by_family.setdefault(family, []).append(event)

    reasons: dict[str, int] = {}
    transitions: dict[str, int] = {}
    for events in by_family.values():
        coded = _latest(e for e in events if e.reason_code)
        if coded is not None and coded.reason_code:
            code = coded.reason_code if coded.reason_code in LEAVING_REASON_CODES else "other"
            reasons[code] = reasons.get(code, 0) + 1
            continue
        latest = _latest(events)
        if latest is not None:
            key = DEPARTURE_TRANSITIONS[latest.event_type][0]
            transitions[key] = transitions.get(key, 0) + 1

    by_reason = tuple(
        ReasonCount(key=code, label=None, families=reasons.get(code, 0))
        for code in LEAVING_REASON_CODES
    )
    by_transition = tuple(
        ReasonCount(key=key, label=_TRANSITION_LABELS[key], families=transitions[key])
        for key in TRANSITION_ORDER
        if transitions.get(key)
    )
    with_reason = sum(reasons.values())
    without_reason = sum(transitions.values())
    return FamiliesLost(
        date_from=date_from,
        date_to=date_to,
        timezone=timezone,
        families_lost=with_reason + without_reason,
        by_reason=by_reason,
        with_reason=with_reason,
        by_transition=by_transition,
        without_reason=without_reason,
    )


class FamiliesLostReport:
    """``GET /admin/reports/people/families-lost?from=&to=``.

    ``from`` and ``to`` are academy-local calendar days, both inclusive
    (default: the last 90 days), matched against the day the departure took
    effect. Who the families are, and whether they have left, is the family
    index's answer (the Families view's Left tile), so the two never disagree.
    """

    def __init__(
        self,
        *,
        index: LostFamiliesIndexSource,
        departures: DepartureSource,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._index = index
        self._departures = departures
        self._academy_timezone = academy_timezone
        self._clock = clock

    async def run(
        self, academy_id: str, *, date_from: date | None = None, date_to: date | None = None
    ) -> FamiliesLost:
        zone, zone_name = _zone(await self._academy_timezone(academy_id))
        today = self._clock().astimezone(zone).date()
        start, end, utc_from, utc_before = _local_day_window(zone, today, date_from, date_to)
        # FamilyIndexUnavailable (a primary source failed) propagates: 503.
        index = await self._index.build(academy_id)
        try:
            events = await self._departures.departures(
                academy_id, effective_from=utc_from, effective_before=utc_before
            )
        except Exception as exc:
            raise PeopleReportUnavailable("departures unavailable") from exc
        return summarize_families_lost(
            index, events, date_from=start, date_to=end, timezone=zone_name
        )
