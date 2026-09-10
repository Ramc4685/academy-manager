"""The composition-root ``ExpectedAbsenceProvider`` for the coach digest (#616)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.composition.digests import _CoachExpectedAbsenceProvider
from backend.v2.contexts.communications.application.digest_renderer import ExpectedAbsence


@dataclass
class FakeOccurrences:
    rows: list[Any] = field(default_factory=list)
    calls: list[tuple[str, date]] = field(default_factory=list)

    async def execute(self, coach_id: str, on_date: date) -> list[Any]:
        self.calls.append((coach_id, on_date))
        return list(self.rows)


@dataclass
class FakeNotices:
    by_occurrence: dict[str, list[Any]] = field(default_factory=dict)

    async def list_for_occurrence(self, occurrence_id: str) -> list[Any]:
        return list(self.by_occurrence.get(occurrence_id, []))


@dataclass
class FakeStudents:
    names: dict[str, str] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    async def by_ids(self, student_ids: list[str]) -> list[Any]:
        self.calls.append(list(student_ids))
        return [
            SimpleNamespace(student_id=sid, full_name=self.names[sid])
            for sid in student_ids
            if sid in self.names
        ]


def _notice(student_id: str, *, window_met: bool = True) -> Any:
    return SimpleNamespace(
        student_id=student_id,
        notice_window_met=window_met,
        submitted_at=datetime(2026, 6, 12, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_lists_notices_per_occurrence_in_occurrence_order_with_names() -> None:
    occurrences = FakeOccurrences(
        rows=[
            SimpleNamespace(occurrence_id="occ-1", title="Tuesday Juniors"),
            SimpleNamespace(occurrence_id="occ-2", title="Evening Adults"),
            SimpleNamespace(occurrence_id="occ-3", title="No notices"),
        ]
    )
    notices = FakeNotices(
        by_occurrence={
            "occ-1": [_notice("st-1"), _notice("st-2", window_met=False)],
            "occ-2": [_notice("st-1")],
        }
    )
    students = FakeStudents(names={"st-1": "Alice", "st-2": "Bob"})
    provider = _CoachExpectedAbsenceProvider(
        occurrences=occurrences, notices=notices, students=students
    )

    rows = await provider.for_coach("coach-1", date(2026, 6, 12))

    assert rows == (
        ExpectedAbsence(session_title="Tuesday Juniors", student_name="Alice"),
        ExpectedAbsence(
            session_title="Tuesday Juniors", student_name="Bob", notice_window_met=False
        ),
        ExpectedAbsence(session_title="Evening Adults", student_name="Alice"),
    )
    assert occurrences.calls == [("coach-1", date(2026, 6, 12))]
    # One batched name lookup, deduped.
    assert students.calls == [["st-1", "st-2"]]


@pytest.mark.asyncio
async def test_no_notices_means_no_rows_and_no_student_lookup() -> None:
    students = FakeStudents()
    provider = _CoachExpectedAbsenceProvider(
        occurrences=FakeOccurrences(rows=[SimpleNamespace(occurrence_id="occ-1", title="T")]),
        notices=FakeNotices(),
        students=students,
    )
    assert await provider.for_coach("coach-1", date(2026, 6, 12)) == ()
    assert students.calls == []


@pytest.mark.asyncio
async def test_unknown_student_gets_a_placeholder_not_a_crash() -> None:
    provider = _CoachExpectedAbsenceProvider(
        occurrences=FakeOccurrences(rows=[SimpleNamespace(occurrence_id="occ-1", title="T")]),
        notices=FakeNotices(by_occurrence={"occ-1": [_notice("st-gone")]}),
        students=FakeStudents(),
    )
    rows = await provider.for_coach("coach-1", date(2026, 6, 12))
    assert rows == (ExpectedAbsence(session_title="T", student_name="A student"),)
