"""A coach swap's follow-up recompute retries a lost race once and shouts when
the period left draft (L7 part 2)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from backend.v2.composition.replacement_payout_snapshots import recompute_draft_payout_periods
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriodConflictError,
    PayoutPeriodStateError,
)

pytestmark = pytest.mark.asyncio


class _Recompute:
    def __init__(self, *outcomes: Exception | None) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    async def execute(self, **_: Any) -> None:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if outcome is not None:
            raise outcome


async def test_a_conflict_is_retried_once_and_then_lands() -> None:
    recompute = _Recompute(PayoutPeriodConflictError("raced"), None)
    await recompute_draft_payout_periods(recompute, period_ids=["pp-1"], actor_id="owner")  # type: ignore[arg-type]
    assert recompute.calls == 2


async def test_two_conflicts_give_up_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    recompute = _Recompute(PayoutPeriodConflictError("a"), PayoutPeriodConflictError("b"))
    with caplog.at_level(logging.WARNING):
        await recompute_draft_payout_periods(recompute, period_ids=["pp-1"], actor_id="owner")  # type: ignore[arg-type]
    assert recompute.calls == 2
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


async def test_a_period_that_left_draft_is_logged_as_an_error_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recompute = _Recompute(PayoutPeriodStateError("approved"), None)
    with caplog.at_level(logging.WARNING):
        await recompute_draft_payout_periods(
            recompute,  # type: ignore[arg-type]
            period_ids=["pp-1", "pp-2"],
            actor_id="owner",
        )
    assert recompute.calls == 2  # pp-1 once, then pp-2
    (record,) = caplog.records
    assert record.levelno == logging.ERROR and "left_draft" in record.getMessage()
