"""A cancelled class is never coach-attended and never paid (issue #671).

``CancelSessionOccurrence`` clears ``is_payable`` and sets the status to
``cancelled``. Payout eligibility must honour BOTH independently: a row that
somehow keeps ``is_payable=True`` (an old document, a hand-edit) still must
not pay, and neither must a row whose flag was cleared but whose status a
later resync restored. These tests pin that, so the guard cannot be dropped
from ``ComputePayout`` without a red build.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.coaching.application.use_cases.compute_payout import ComputeCoachPayout
from backend.v2.contexts.coaching.domain.payout import CoachRate, PayableOccurrence

PERIOD_START = datetime(2026, 9, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 10, 1, tzinfo=UTC)
START = datetime(2026, 9, 10, 23, 0, tzinfo=UTC)


class FakeOccurrences:
    def __init__(self, rows: list[PayableOccurrence]) -> None:
        self._rows = rows

    async def list_in_period(
        self, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list[PayableOccurrence]:
        return list(self._rows)


class FakeRates:
    def __init__(self, rates: list[CoachRate]) -> None:
        self._rates = rates

    async def list_for_coach(self, coach_id: str) -> list[CoachRate]:
        return list(self._rates)

    async def find_for_coach_at(self, coach_id: str, at_time: datetime) -> CoachRate | None:
        for rate in self._rates:
            if rate.coach_id == coach_id and rate.effective_from <= at_time:
                return rate
        return None


def _occurrence(occurrence_id: str, *, status: str, is_payable: bool) -> PayableOccurrence:
    return PayableOccurrence(
        occurrence_id=occurrence_id,
        academy_id="acad",
        start_at=START,
        end_at=START + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        scheduled_coach_id="coach-1",
        is_payable=is_payable,
    )


def _rate() -> CoachRate:
    return CoachRate(
        rate_id="rate-1",
        academy_id="acad",
        coach_id="coach-1",
        billing_unit="per_session",
        amount_minor=5000,
        currency="usd",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def _statement(rows: list[PayableOccurrence]):
    use_case = ComputeCoachPayout(
        FakeOccurrences(rows),  # type: ignore[arg-type]
        FakeRates([_rate()]),  # type: ignore[arg-type]
    )
    return await use_case.execute(
        coach_id="coach-1",
        academy_id="acad",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )


@pytest.mark.asyncio
async def test_a_completed_payable_class_is_paid() -> None:
    statement = await _statement([_occurrence("occ-ok", status="completed", is_payable=True)])
    assert [line.occurrence_id for line in statement.lines] == ["occ-ok"]
    assert statement.total_minor == 5000


@pytest.mark.asyncio
async def test_a_cancelled_class_is_not_paid_even_if_still_flagged_payable() -> None:
    statement = await _statement(
        [_occurrence("occ-cancelled", status="cancelled", is_payable=True)]
    )
    assert statement.lines == []
    assert statement.total_minor == 0


@pytest.mark.asyncio
async def test_an_unpayable_class_is_not_paid_even_if_status_says_completed() -> None:
    statement = await _statement(
        [_occurrence("occ-unpayable", status="completed", is_payable=False)]
    )
    assert statement.lines == []
    assert statement.total_minor == 0


@pytest.mark.asyncio
async def test_cancelling_one_date_leaves_the_rest_of_the_month_paid() -> None:
    statement = await _statement(
        [
            _occurrence("occ-1", status="completed", is_payable=True),
            _occurrence("occ-2", status="cancelled", is_payable=False),
            _occurrence("occ-3", status="completed", is_payable=True),
        ]
    )
    assert sorted(line.occurrence_id for line in statement.lines) == ["occ-1", "occ-3"]
    assert statement.total_minor == 10000
