"""The hourly dunning tick across academies (L1: findings A4-9, A7-1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.v2.main import _run_dunning_for_academies
from backend.v2.shared.tenancy.context import current_academy_id


class _Worker:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.called: list[str] = []

    async def execute(self, *, limit: int, worker_id: str):
        academy_id = current_academy_id()
        self.called.append(academy_id)
        if academy_id in self.fail_for:
            raise ValueError("dunning state changed during park; retry")
        return SimpleNamespace(processed=2, parked=1, technical_failures=1, succeeded=1)


@pytest.mark.asyncio
async def test_one_academys_dunning_failure_does_not_abort_the_rest() -> None:
    worker = _Worker(fail_for={"academy-bad"})

    totals = await _run_dunning_for_academies(
        academy_ids=["academy-bad", "academy-good"],
        late_fees=None,
        worker=worker,
    )

    assert worker.called == ["academy-bad", "academy-good"]
    assert totals["academy_count"] == 1
    assert totals["academy_failures"] == 1
    assert totals["processed"] == 2


@pytest.mark.asyncio
async def test_parked_and_technical_failures_are_carried_into_totals() -> None:
    totals = await _run_dunning_for_academies(
        academy_ids=["a", "b"], late_fees=None, worker=_Worker()
    )

    assert totals["parked"] == 2
    assert totals["technical_failures"] == 2
