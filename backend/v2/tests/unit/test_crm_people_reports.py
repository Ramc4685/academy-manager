"""Unit tests for the People reports' pure pieces (roadmap L5a).

The Mongo-backed behaviour (billing's balance rule, band boundaries, parity
with the family index, tenant isolation) is proven on a real ``mongod`` in
``tests/contract/test_people_reports_real_db.py``; this file pins the band
arithmetic and the inquiry window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.crm.application.people_reports import (
    MAX_WINDOW_DAYS,
    InquiryConversionReport,
    InvalidReportRange,
    MoneyOwedByAgeReport,
    PeopleReportUnavailable,
    age_family_money,
    summarize_inquiry_conversion,
)
from backend.v2.contexts.crm.domain.family_index import FamilyIndex
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id, tenant_scope

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Facts:
    balance_cents: int = 0
    overdue_cents: int = 0


def test_bands_are_differences_of_the_shifted_overdue_answers() -> None:
    report = age_family_money(
        as_of=date(2026, 9, 23),
        generated_at=NOW,
        due_before_today={"a": Facts(10_000, 9_000), "b": Facts(500, 0), "c": Facts(0, 0)},
        due_before_day_30={"a": Facts(10_000, 6_000)},
        due_before_day_60={"a": Facts(10_000, 1_000)},
    )
    assert [(b.key, b.family_count, b.total_cents) for b in report.bands] == [
        ("days_1_30", 1, 3_000),
        ("days_31_60", 1, 5_000),
        ("days_over_60", 1, 1_000),
    ]
    assert (report.not_yet_due.family_count, report.not_yet_due.total_cents) == (2, 1_500)
    assert report.overdue_cents == 9_000
    assert report.balance_cents == 10_500
    assert report.owing_family_count == 2
    assert report.overdue_family_count == 1


def test_a_band_never_goes_negative_if_money_moved_between_reads() -> None:
    report = age_family_money(
        as_of=date(2026, 9, 23),
        generated_at=NOW,
        due_before_today={"a": Facts(1_000, 1_000)},
        due_before_day_30={"a": Facts(3_000, 3_000)},  # paid down in between
        due_before_day_60={"a": Facts(3_000, 0)},
    )
    assert [b.total_cents for b in report.bands] == [0, 3_000, 0]


class _Index:
    async def build(self, academy_id: str) -> FamilyIndex:
        return FamilyIndex(
            academy_id=academy_id,
            generated_at=NOW,
            families=(),
            warnings=(),
            family_by_alias={"fb-a": "u-a", "u-a": "u-a"},
        )

    async def academy_today(self, academy_id: str) -> date:
        return date(2026, 9, 23)


class _Money:
    def __init__(self, fail: bool = False) -> None:
        self.days: list[date] = []
        self.fail = fail

    async def summaries(self, *, academy_id: str, family_by_alias, today: date):  # type: ignore[no-untyped-def]
        if self.fail:
            raise RuntimeError("billing down")
        self.days.append(today)
        assert family_by_alias == {"fb-a": "u-a", "u-a": "u-a"}
        return {"u-a": Facts(100, 0)}


async def test_money_report_asks_billing_for_today_and_30_and_60_days_back() -> None:
    money = _Money()
    report = await MoneyOwedByAgeReport(index=_Index(), money=money, clock=lambda: NOW).run("acad")
    assert money.days == [date(2026, 9, 23), date(2026, 8, 24), date(2026, 7, 25)]
    assert report.balance_cents == 100


async def test_money_failure_raises_rather_than_reporting_zero() -> None:
    with pytest.raises(PeopleReportUnavailable):
        await MoneyOwedByAgeReport(index=_Index(), money=_Money(fail=True)).run("acad")


def test_unknown_source_and_status_are_counted_not_dropped() -> None:
    result = summarize_inquiry_conversion(
        [("fax", "lead", 1), ("website", "mystery", 2), ("website", "enrolled", 1)],
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        timezone="UTC",
    )
    rows = {r.source: r for r in result.sources}
    assert rows["other"].inquiries == 1
    assert (rows["website"].lead, rows["website"].enrolled) == (2, 1)
    assert result.total.inquiries == 4


class _Contacts:
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, datetime]] = []

    async def count_by_source_and_status(
        self, *, created_from: datetime, created_before: datetime
    ) -> list[tuple[str, str, int]]:
        self.calls.append((created_from, created_before))
        return []


async def _tz(name: str | None):  # type: ignore[no-untyped-def]
    async def lookup(academy_id: str) -> str | None:
        return name

    return lookup


async def test_window_is_academy_local_days_and_falls_back_to_utc() -> None:
    contacts = _Contacts()
    report = InquiryConversionReport(
        contacts=contacts, academy_timezone=await _tz("America/Chicago"), clock=lambda: NOW
    )
    result = await report.run("acad", date_from=date(2026, 9, 1), date_to=date(2026, 9, 10))
    assert contacts.calls == [
        (datetime(2026, 9, 1, 5, 0, tzinfo=UTC), datetime(2026, 9, 11, 5, 0, tzinfo=UTC))
    ]
    assert result.timezone == "America/Chicago"

    contacts = _Contacts()
    report = InquiryConversionReport(
        contacts=contacts, academy_timezone=await _tz(None), clock=lambda: NOW
    )
    result = await report.run("acad")
    assert (result.date_from, result.date_to, result.timezone) == (
        date(2026, 6, 26),
        date(2026, 9, 23),
        "UTC",
    )
    assert contacts.calls == [
        (datetime(2026, 6, 26, tzinfo=UTC), datetime(2026, 9, 24, tzinfo=UTC))
    ]


async def test_window_validation() -> None:
    report = InquiryConversionReport(
        contacts=_Contacts(), academy_timezone=await _tz("UTC"), clock=lambda: NOW
    )
    with pytest.raises(InvalidReportRange):
        await report.run("acad", date_from=date(2026, 9, 2), date_to=date(2026, 9, 1))
    with pytest.raises(InvalidReportRange):
        await report.run("acad", date_from=date(2020, 1, 1), date_to=date(2026, 9, 1))
    # Exactly the cap is fine.
    end = date(2026, 9, 1)
    start = date.fromordinal(end.toordinal() - MAX_WINDOW_DAYS + 1)
    result = await report.run("acad", date_from=start, date_to=end)
    assert result.date_from == start


class _ScopedContacts:
    """Mirrors MongoCrmContactRepository: the academy comes from the ContextVar."""

    def __init__(self) -> None:
        self.academies: list[str] = []

    async def count_by_source_and_status(
        self, *, created_from: datetime, created_before: datetime
    ) -> list[tuple[str, str, int]]:
        self.academies.append(current_academy_id())
        return []


async def test_contacts_are_counted_for_the_academy_the_run_was_asked_for() -> None:
    contacts = _ScopedContacts()
    report = InquiryConversionReport(
        contacts=contacts, academy_timezone=await _tz("UTC"), clock=lambda: NOW
    )
    # No tenant context (the route's claims fallback): still scoped, no raise.
    await report.run("acad-a")
    # A stale context never wins over the academy passed in.
    with tenant_scope("acad-other"):
        await report.run("acad-b")
        assert current_academy_id() == "acad-other"
    assert contacts.academies == ["acad-a", "acad-b"]
    with pytest.raises(TenantContextUnset):
        current_academy_id()
