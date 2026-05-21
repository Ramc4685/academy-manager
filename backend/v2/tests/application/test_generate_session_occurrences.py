"""Use-case tests for durable session occurrence generation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.v2.contexts.enrollment.application.use_cases.generate_session_occurrences import (
    GenerateSessionOccurrences,
    GenerateSessionOccurrencesCommand,
)
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence


class FakeOccurrenceRepo:
    def __init__(self) -> None:
        self.saved: list[SessionOccurrence] = []

    async def list_for_session_between(
        self,
        *,
        session_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SessionOccurrence]:
        return [
            occurrence
            for occurrence in self.saved
            if occurrence.session_id == session_id and start_at <= occurrence.start_at <= end_at
        ]

    async def save_many(self, occurrences: list[SessionOccurrence]) -> None:
        existing = {(row.session_id, row.start_at) for row in self.saved}
        for occurrence in occurrences:
            key = (occurrence.session_id, occurrence.start_at)
            if key not in existing:
                self.saved.append(occurrence)
                existing.add(key)


def _session() -> Session:
    return Session(
        session_id="sess-1",
        academy_id="academy-a",
        coach_id="coach-1",
        title="Junior A",
        location="Court 1",
        start_at=datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc),
        capacity=8,
    )


@pytest.mark.asyncio
async def test_generates_weekly_occurrences_from_recurring_session() -> None:
    repo = FakeOccurrenceRepo()
    use_case = GenerateSessionOccurrences(repo)

    result = await use_case.execute(
        session=_session(),
        cmd=GenerateSessionOccurrencesCommand(
            range_start=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
            range_end=datetime(2026, 6, 22, 23, 59, tzinfo=timezone.utc),
        ),
    )

    assert [row.start_at.day for row in result] == [1, 8, 15, 22]
    assert [row.end_at.hour for row in result] == [19, 19, 19, 19]
    assert {row.session_id for row in result} == {"sess-1"}
    assert {row.scheduled_coach_id for row in result} == {"coach-1"}
    assert all(row.is_billable and row.is_payable for row in result)


@pytest.mark.asyncio
async def test_generation_is_idempotent_for_existing_occurrences() -> None:
    repo = FakeOccurrenceRepo()
    use_case = GenerateSessionOccurrences(repo)
    cmd = GenerateSessionOccurrencesCommand(
        range_start=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
        range_end=datetime(2026, 6, 15, 23, 59, tzinfo=timezone.utc),
    )

    first = await use_case.execute(session=_session(), cmd=cmd)
    second = await use_case.execute(session=_session(), cmd=cmd)

    assert [row.occurrence_id for row in second] == [row.occurrence_id for row in first]
    assert len(repo.saved) == 3
