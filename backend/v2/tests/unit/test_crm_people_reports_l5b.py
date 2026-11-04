"""Unit tests for the L5b People reports: attendance risk and families lost.

The groupings are pure functions over facts the real-DB tests produce from
Mongo; these pin the counting rules, the ordering and the vocabularies the
CRM context spells again because contexts may not import each other.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.crm.application.people_reports import (
    DEPARTURE_TRANSITIONS,
    LEAVING_REASON_CODES,
    AttendanceRiskFacts,
    AttendanceRiskReport,
    DepartureFact,
    FamiliesLostReport,
    InvalidReportRange,
    PeopleReportUnavailable,
    RiskClass,
    RiskStudent,
    summarize_attendance_risk,
    summarize_families_lost,
)
from backend.v2.contexts.crm.domain.family_index import FamilyChild, FamilyIndex, FamilyRecord
from backend.v2.contexts.crm.domain.family_stage import roll_up_family_stage
from backend.v2.contexts.enrollment.application.use_cases.departure_reasons import (
    DEPARTURE_REASON_CODES,
)
from backend.v2.contexts.enrollment.application.use_cases.leaving_report import (
    DEPARTURE_EVENT_TYPES,
)

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def test_vocabularies_match_the_enrollment_context() -> None:
    assert LEAVING_REASON_CODES == DEPARTURE_REASON_CODES
    assert frozenset(DEPARTURE_TRANSITIONS) == DEPARTURE_EVENT_TYPES


# ------------------------------------------------------------ attendance risk


def _facts() -> AttendanceRiskFacts:
    return AttendanceRiskFacts(
        students=(
            RiskStudent("s1", "at_risk", ("c-tue", "c-thu")),
            RiskStudent("s2", "active", ("c-tue",)),
            RiskStudent("s3", "at_risk", ("c-sat",)),
            RiskStudent("s4", "pending_cancel", ("c-sat",)),
            RiskStudent("s5", "left", ()),
            RiskStudent("s6", "active", ("c-gone",)),
        ),
        classes={
            "c-tue": RiskClass("c-tue", "Tuesday", "coach-1"),
            "c-thu": RiskClass("c-thu", "Thursday", "coach-1"),
            "c-sat": RiskClass("c-sat", "Saturday", None),
        },
        coach_names={"coach-1": "Testcoach One"},
    )


def test_attendance_risk_groups_by_class_then_coach() -> None:
    report = summarize_attendance_risk(_facts(), generated_at=NOW)

    assert [(r.session_id, r.students, r.at_risk, r.at_risk_rate) for r in report.by_class] == [
        ("c-thu", 1, 1, 1.0),
        ("c-sat", 2, 1, 0.5),
        ("c-tue", 2, 1, 0.5),
        # A seat in a class with no document still counts, under its id.
        ("c-gone", 1, 0, 0.0),
    ]
    by_class = {r.session_id: r for r in report.by_class}
    assert by_class["c-gone"].title == "c-gone"
    assert by_class["c-tue"].coach_name == "Testcoach One"
    assert [(r.coach_id, r.classes, r.students, r.at_risk) for r in report.by_coach] == [
        # s1 sits in two of coach 1's classes: one student for the coach.
        ("coach-1", 2, 2, 1),
        (None, 2, 3, 1),
    ]
    assert report.by_coach[0].coach_name == "Testcoach One"
    # s5 holds no seat; s1 is one student however many classes.
    assert (report.students, report.at_risk) == (5, 2)


def test_attendance_risk_with_no_seats_is_empty() -> None:
    report = summarize_attendance_risk(
        AttendanceRiskFacts(students=(), classes={}, coach_names={}), generated_at=NOW
    )
    assert (report.by_class, report.by_coach, report.students, report.at_risk) == ((), (), 0, 0)


class _BrokenSource:
    async def facts(self, academy_id: str) -> AttendanceRiskFacts:
        raise RuntimeError("mongo down")


async def test_attendance_risk_source_failure_is_unavailable_not_zero() -> None:
    with pytest.raises(PeopleReportUnavailable):
        await AttendanceRiskReport(source=_BrokenSource()).run("acad")


# ------------------------------------------------------------ families lost


def _family(family_id: str, *children: tuple[str, str]) -> FamilyRecord:
    kids = tuple(FamilyChild(student_id=sid, name=sid, lifecycle=state) for sid, state in children)
    return FamilyRecord(
        family_id=family_id,
        parent_name=None,
        email=None,
        phone=None,
        has_account=False,
        children=kids,
        stage=roll_up_family_stage(k.lifecycle for k in kids),
    )


def _index() -> FamilyIndex:
    return FamilyIndex(
        academy_id="acad",
        generated_at=NOW,
        families=(
            _family("f-coded", ("a1", "left"), ("a2", "left")),
            _family("f-uncoded", ("b1", "left")),
            _family("f-unknown-code", ("c1", "left")),
            _family("f-split", ("d1", "left"), ("d2", "active")),
            _family("f-no-event", ("e1", "left")),
        ),
    )


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, 17, 0, tzinfo=UTC)


def test_families_lost_uses_the_latest_coded_reason_else_the_transition() -> None:
    events = [
        DepartureFact("a1", "withdrawn", "cost", _at(1)),
        DepartureFact("a2", "dropped", "moved_away", _at(3)),
        # A later uncoded departure does not erase the recorded reason.
        DepartureFact("a2", "cancelled", None, _at(5)),
        DepartureFact("b1", "dropped", None, _at(2)),
        DepartureFact("b1", "hold_expired", None, _at(4)),
        DepartureFact("c1", "withdrawn", "made_up_code", _at(2)),
        DepartureFact("d1", "withdrawn", "cost", _at(2)),
        # Not a departure: ignored.
        DepartureFact("b1", "enrolled", "cost", _at(6)),
        # A student the index does not know.
        DepartureFact("zz", "withdrawn", "cost", _at(2)),
    ]
    report = summarize_families_lost(
        _index(), events, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), timezone="UTC"
    )

    assert report.families_lost == 3
    assert {r.key: r.families for r in report.by_reason if r.families} == {
        "moved_away": 1,
        "other": 1,
    }
    assert [r.key for r in report.by_reason] == list(LEAVING_REASON_CODES)
    assert report.with_reason == 2
    assert [(r.key, r.label, r.families) for r in report.by_transition] == [
        ("hold_expired", "Hold ran out", 1)
    ]
    assert report.without_reason == 1


class _Index:
    async def build(self, academy_id: str) -> FamilyIndex:
        return _index()


class _Departures:
    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime, datetime]] = []

    async def departures(
        self, academy_id: str, *, effective_from: datetime, effective_before: datetime
    ) -> list[DepartureFact]:
        self.calls.append((academy_id, effective_from, effective_before))
        return []


async def _chicago(academy_id: str) -> str | None:
    return "America/Chicago"


async def test_families_lost_window_is_academy_local_days() -> None:
    departures = _Departures()
    report = await FamiliesLostReport(
        index=_Index(), departures=departures, academy_timezone=_chicago, clock=lambda: NOW
    ).run("acad", date_from=date(2026, 9, 1), date_to=date(2026, 9, 15))

    assert (report.date_from, report.date_to, report.timezone) == (
        date(2026, 9, 1),
        date(2026, 9, 15),
        "America/Chicago",
    )
    assert departures.calls == [
        (
            "acad",
            datetime(2026, 9, 1, 5, 0, tzinfo=UTC),
            datetime(2026, 9, 16, 5, 0, tzinfo=UTC),
        )
    ]
    assert report.families_lost == 0


async def test_families_lost_defaults_to_the_last_90_days_and_rejects_bad_ranges() -> None:
    lost = FamiliesLostReport(
        index=_Index(), departures=_Departures(), academy_timezone=_chicago, clock=lambda: NOW
    )
    report = await lost.run("acad")
    assert (report.date_from, report.date_to) == (date(2026, 6, 26), date(2026, 9, 23))
    with pytest.raises(InvalidReportRange):
        await lost.run("acad", date_from=date(2026, 9, 2), date_to=date(2026, 9, 1))


class _BrokenDepartures:
    async def departures(
        self, academy_id: str, *, effective_from: datetime, effective_before: datetime
    ) -> list[DepartureFact]:
        raise RuntimeError("mongo down")


async def test_families_lost_departure_failure_is_unavailable() -> None:
    with pytest.raises(PeopleReportUnavailable):
        await FamiliesLostReport(
            index=_Index(), departures=_BrokenDepartures(), academy_timezone=_chicago
        ).run("acad")
