"""The coaching-to-finance payout seam, driven with real models.

Every other payout test feeds GeneratePayoutPeriod a fake calculation that
already speaks finance types, which hid the persona-test P1: a coach with an
unpaid class made Generate return 500 because the adapter passed coaching's
PayoutUnpaidOccurrence into PayoutPeriod.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.v2.contexts.coaching.domain.payout import (
    PayoutLine,
    PayoutStatement,
    PayoutUnpaidOccurrence,
)
from backend.v2.contexts.finance.application.payout_calculator import FinancePayoutCalculator
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    GeneratePayoutPeriod,
)
from backend.v2.contexts.finance.domain.payout_period import PersistedUnpaidOccurrence
from backend.v2.tests.application.test_payout_period import CollectingAudit, FakeRepo

START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)


class _Computer:
    """Returns a real coaching statement, as ComputeCoachPayout does."""

    def __init__(self, statement: PayoutStatement) -> None:
        self._statement = statement

    async def execute(self, **_: object) -> PayoutStatement:
        return self._statement

    async def execute_many(self, *, coach_ids: list[str], **_: object) -> dict[str, PayoutStatement]:
        return {coach_id: self._statement for coach_id in coach_ids}


def _statement() -> PayoutStatement:
    return PayoutStatement(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=START,
        period_end=END,
        currency="USD",
        lines=[
            PayoutLine(
                occurrence_id="occ-paid",
                coach_id="coach-A",
                basis="scheduled",
                minutes=Decimal(60),
                amount_minor=2500,
                currency="USD",
                rate_id="rate-1",
            )
        ],
        total_minor=2500,
        unpaid_occurrence_ids=["occ-unpaid"],
        unpaid_occurrences=[
            PayoutUnpaidOccurrence(
                occurrence_id="occ-unpaid",
                reason="no_rate_configured",
                detail="No rate on file.",
            )
        ],
    )


async def test_generate_with_unpaid_class_through_real_adapter() -> None:
    repo = FakeRepo()
    generate = GeneratePayoutPeriod(
        calculator=FinancePayoutCalculator(_Computer(_statement())),
        repository=repo,
        audit=CollectingAudit(),
    )

    period = await generate.execute(
        coach_id="coach-A", academy_id="acad-1", period_start=START, period_end=END
    )

    assert period.total_minor == 2500
    assert period.unpaid_occurrence_ids == ["occ-unpaid"]
    assert [type(u) for u in period.unpaid_occurrences] == [PersistedUnpaidOccurrence]
    assert period.unpaid_occurrences[0].reason == "no_rate_configured"
