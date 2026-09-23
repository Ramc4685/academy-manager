"""People reports: money owed by age band and inquiry conversion by source.

Two read-only cards on ``/admin/reports`` (roadmap item L5a):

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

Money is gated at the interface by ``can_view_family_money``; the inquiry
counts carry no money.
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


class InquiryConversionReport:
    """``GET /admin/reports/people/inquiry-conversion?from=&to=``.

    ``from`` and ``to`` are academy-local calendar days, both inclusive; the
    window is ``[from 00:00, to + 1 day 00:00)`` in the academy's timezone.
    Contacts are read through the tenant-scoped repository, so only the
    request's academy is ever counted.
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
        end = date_to or today
        start = date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS - 1))
        if start > end:
            raise InvalidReportRange("from must be on or before to")
        if (end - start).days + 1 > MAX_WINDOW_DAYS:
            raise InvalidReportRange(f"the window may be at most {MAX_WINDOW_DAYS} days")
        created_from = datetime.combine(start, time.min, tzinfo=zone).astimezone(UTC)
        created_before = datetime.combine(
            end + timedelta(days=1), time.min, tzinfo=zone
        ).astimezone(UTC)
        rows = await self._contacts.count_by_source_and_status(
            created_from=created_from, created_before=created_before
        )
        return summarize_inquiry_conversion(rows, date_from=start, date_to=end, timezone=zone_name)
