"""Coach payout — domain + use case tests (Wave 4A).

Coach payout combines two Wave 3 outputs:

- ``SessionOccurrence`` (enrollment context) gives us dated, status-aware
  events with three coach fields: ``scheduled_coach_id``,
  ``substitute_coach_id``, ``actual_coach_id``.
- ``billing_ledger`` (billing context) is the source of truth for academy
  revenue side, but payout is computed independently from occurrences plus a
  per-coach rate sheet — we do NOT couple payout to invoice payment status.

Attribution rule (single paying coach per occurrence):

    actual_coach_id ?? substitute_coach_id ?? scheduled_coach_id

Eligibility rule (an occurrence pays out iff):

    status == "completed" AND is_payable is True

Rate selection:

- A ``CoachRate`` is effective at occurrence ``start_at`` when
  ``effective_from <= start_at < (effective_until or +inf)``.
- If no rate matches, the occurrence is skipped and reported as unpaid
  (so the statement still totals correctly).

Amount math:

- ``per_session`` rates pay ``rate.amount_minor`` once per occurrence.
- ``per_hour`` rates pay
  ``round_half_even(amount_minor * minutes / 60)``
  where minutes = (end_at - start_at).total_seconds() / 60.

These tests use in-memory fakes; Mongo wiring is out of scope for this
slice — coach rate storage lands when the admin UI for rates lands.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.coaching.application.use_cases.compute_payout import (
    ComputeCoachPayout,
)
from backend.v2.contexts.coaching.domain.payout import (
    CoachRate,
    PayableOccurrence,
    PayoutLine,
    PayoutStatement,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _occurrence(
    occurrence_id: str,
    *,
    start: str,
    end: str,
    status: str = "completed",
    is_payable: bool = True,
    scheduled_coach_id: str = "coach-A",
    actual_coach_id: str | None = None,
    substitute_coach_id: str | None = None,
    academy_id: str = "acad-1",
) -> PayableOccurrence:
    return PayableOccurrence(
        occurrence_id=occurrence_id,
        academy_id=academy_id,
        start_at=_dt(start),
        end_at=_dt(end),
        status=status,
        scheduled_coach_id=scheduled_coach_id,
        actual_coach_id=actual_coach_id,
        substitute_coach_id=substitute_coach_id,
        is_payable=is_payable,
    )


class FakeOccurrenceQuery:
    def __init__(self, occurrences: list[PayableOccurrence]) -> None:
        self._items = list(occurrences)

    async def list_in_period(
        self,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[PayableOccurrence]:
        return [
            o
            for o in self._items
            if o.academy_id == academy_id and period_start <= o.start_at < period_end
        ]


class FakeRateRepo:
    def __init__(self, rates: list[CoachRate]) -> None:
        self._rates = list(rates)

    async def find_for_coach_at(self, coach_id: str, at_time: datetime) -> CoachRate | None:
        candidates = [
            r
            for r in self._rates
            if r.coach_id == coach_id
            and r.effective_from <= at_time
            and (r.effective_until is None or at_time < r.effective_until)
        ]
        if not candidates:
            return None
        # Most-recently-effective wins if multiple match (shouldn't happen
        # with active rates, but be defensive).
        return max(candidates, key=lambda r: r.effective_from)


# ---------------------------------------------------------------------------
# Domain shape
# ---------------------------------------------------------------------------


def test_coach_rate_requires_academy_coach_and_amount() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    assert rate.academy_id == "acad-1"
    assert rate.coach_id == "coach-A"
    assert rate.amount_minor == 5000


def test_payout_line_carries_attribution_basis() -> None:
    line = PayoutLine(
        occurrence_id="occ-1",
        coach_id="coach-A",
        basis="scheduled",
        minutes=Decimal("60"),
        amount_minor=5000,
        currency="USD",
        rate_id="cr-1",
    )
    assert line.basis == "scheduled"
    assert line.amount_minor == 5000


def test_payout_statement_totals_match_sum_of_lines() -> None:
    statement = PayoutStatement(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        currency="USD",
        lines=[
            PayoutLine(
                occurrence_id="occ-1",
                coach_id="coach-A",
                basis="scheduled",
                minutes=Decimal("60"),
                amount_minor=5000,
                currency="USD",
                rate_id="cr-1",
            ),
            PayoutLine(
                occurrence_id="occ-2",
                coach_id="coach-A",
                basis="scheduled",
                minutes=Decimal("90"),
                amount_minor=7500,
                currency="USD",
                rate_id="cr-1",
            ),
        ],
        total_minor=12500,
        unpaid_occurrence_ids=[],
    )
    assert sum(line.amount_minor for line in statement.lines) == statement.total_minor


# ---------------------------------------------------------------------------
# Attribution rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actual_coach_id_takes_precedence_over_substitute_and_scheduled() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-actual",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occ = _occurrence(
        "occ-1",
        start="2026-05-10T18:00:00",
        end="2026-05-10T19:00:00",
        scheduled_coach_id="coach-scheduled",
        substitute_coach_id="coach-sub",
        actual_coach_id="coach-actual",
    )
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery([occ]),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-actual",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert len(statement.lines) == 1
    assert statement.lines[0].basis == "actual"
    assert statement.total_minor == 5000


@pytest.mark.asyncio
async def test_substitute_paid_when_no_actual_set() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-sub",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occ = _occurrence(
        "occ-1",
        start="2026-05-10T18:00:00",
        end="2026-05-10T19:00:00",
        scheduled_coach_id="coach-scheduled",
        substitute_coach_id="coach-sub",
        actual_coach_id=None,
    )
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery([occ]),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-sub",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert len(statement.lines) == 1
    assert statement.lines[0].basis == "substitute"


@pytest.mark.asyncio
async def test_scheduled_coach_does_not_get_paid_when_substitute_covered() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-scheduled",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occ = _occurrence(
        "occ-1",
        start="2026-05-10T18:00:00",
        end="2026-05-10T19:00:00",
        scheduled_coach_id="coach-scheduled",
        substitute_coach_id="coach-sub",
        actual_coach_id=None,
    )
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery([occ]),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-scheduled",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert statement.lines == []
    assert statement.total_minor == 0


# ---------------------------------------------------------------------------
# Eligibility rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_completed_occurrences_pay() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occs = [
        _occurrence(
            "occ-1", start="2026-05-10T18:00:00", end="2026-05-10T19:00:00", status="completed"
        ),
        _occurrence(
            "occ-2", start="2026-05-11T18:00:00", end="2026-05-11T19:00:00", status="scheduled"
        ),
        _occurrence(
            "occ-3", start="2026-05-12T18:00:00", end="2026-05-12T19:00:00", status="cancelled"
        ),
    ]
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery(occs),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert {ln.occurrence_id for ln in statement.lines} == {"occ-1"}


@pytest.mark.asyncio
async def test_non_payable_occurrences_are_skipped() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occ = _occurrence(
        "occ-1",
        start="2026-05-10T18:00:00",
        end="2026-05-10T19:00:00",
        is_payable=False,
    )
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery([occ]),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert statement.lines == []


# ---------------------------------------------------------------------------
# Rate selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_in_effect_at_occurrence_start_is_used() -> None:
    old_rate = CoachRate(
        rate_id="cr-old",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=4000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=_dt("2026-05-01T00:00:00"),
        status="superseded",
    )
    new_rate = CoachRate(
        rate_id="cr-new",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-05-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occ = _occurrence(
        "occ-1",
        start="2026-05-10T18:00:00",
        end="2026-05-10T19:00:00",
    )
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery([occ]),
        rates=FakeRateRepo([old_rate, new_rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert statement.lines[0].rate_id == "cr-new"
    assert statement.lines[0].amount_minor == 5000


@pytest.mark.asyncio
async def test_missing_rate_marks_occurrence_unpaid_but_does_not_crash() -> None:
    occ = _occurrence(
        "occ-1",
        start="2026-05-10T18:00:00",
        end="2026-05-10T19:00:00",
    )
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery([occ]),
        rates=FakeRateRepo([]),
    )
    statement = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert statement.lines == []
    assert statement.total_minor == 0
    assert statement.unpaid_occurrence_ids == ["occ-1"]


# ---------------------------------------------------------------------------
# Amount math
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_hour_rate_prorates_partial_hour() -> None:
    # 90 minutes at $50/hr -> $75.00 -> 7500 minor units
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_hour",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occ = _occurrence(
        "occ-1",
        start="2026-05-10T18:00:00",
        end="2026-05-10T19:30:00",
    )
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery([occ]),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert statement.lines[0].amount_minor == 7500
    assert statement.lines[0].minutes == Decimal("90")


@pytest.mark.asyncio
async def test_multiple_occurrences_sum_into_total() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occs = [
        _occurrence("occ-1", start="2026-05-10T18:00:00", end="2026-05-10T19:00:00"),
        _occurrence("occ-2", start="2026-05-17T18:00:00", end="2026-05-17T19:00:00"),
        _occurrence("occ-3", start="2026-05-24T18:00:00", end="2026-05-24T19:00:00"),
    ]
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery(occs),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert len(statement.lines) == 3
    assert statement.total_minor == 15000


@pytest.mark.asyncio
async def test_period_window_excludes_occurrences_outside_range() -> None:
    rate = CoachRate(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=5000,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    occs = [
        _occurrence("occ-april", start="2026-04-30T18:00:00", end="2026-04-30T19:00:00"),
        _occurrence("occ-may", start="2026-05-15T18:00:00", end="2026-05-15T19:00:00"),
        _occurrence("occ-june", start="2026-06-02T18:00:00", end="2026-06-02T19:00:00"),
    ]
    use_case = ComputeCoachPayout(
        occurrences=FakeOccurrenceQuery(occs),
        rates=FakeRateRepo([rate]),
    )
    statement = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert {ln.occurrence_id for ln in statement.lines} == {"occ-may"}
