"""The once-per-academy-local-day claim against real Mongo (Settings Phase 4).

mongomock stands in for the replay tests; this pins the two Mongo behaviours
the claim relies on, with and without migration 0210's indexes: a duplicate
``_id`` insert is a DuplicateKeyError, and only a failed (or stale running)
marker is re-claimable, within the attempt budget.
"""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.shared.scheduling.local_clock import (
    MARKERS_COLLECTION,
    MAX_ATTEMPTS,
    LocalDailyTime,
    claim_local_run,
    run_daily_at_local_time,
)

_M0210 = importlib.import_module("backend.v2.migrations.0210_scheduler_run_markers")

DAY = date(2026, 9, 29)
TICK = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)  # 03:00 Chicago


async def _zone(_academy_id: str) -> str:
    return "America/Chicago"


@pytest.mark.parametrize("with_indexes", [True, False], ids=["0210-applied", "0210-missing"])
async def test_claim_is_once_per_local_day_and_retries_only_failures(
    real_db: Any, with_indexes: bool
) -> None:
    if with_indexes:
        await _M0210.up(real_db)
    claim = {"job": "generate_monthly_invoices", "academy_id": "acad_blno_badminton"}

    assert await claim_local_run(real_db, local_date=DAY, now=TICK, worker_id="a", **claim)
    assert not await claim_local_run(
        real_db, local_date=DAY, now=TICK + timedelta(hours=1), worker_id="b", **claim
    )
    assert await claim_local_run(
        real_db, local_date=DAY + timedelta(days=1), now=TICK, worker_id="a", **claim
    )


async def test_a_failing_academy_retries_within_the_budget_and_never_blocks_another(
    real_db: Any,
) -> None:
    await _M0210.up(real_db)
    runs: list[str] = []

    async def run(academy_id: str, _local_now: datetime) -> None:
        runs.append(academy_id)
        if academy_id == "broken":
            raise RuntimeError("boom")

    for hour in range(6):
        await run_daily_at_local_time(
            db=real_db,
            job="expire_due_holds",
            at=LocalDailyTime(2, 45),
            academy_ids=["broken", "acad_blno_badminton"],
            zone_for=_zone,
            run=run,
            now=TICK + timedelta(hours=hour),
            worker_id="w",
        )

    assert runs.count("acad_blno_badminton") == 1
    assert runs.count("broken") == MAX_ATTEMPTS
    docs = {d["academy_id"]: d async for d in real_db[MARKERS_COLLECTION].find({})}
    assert docs["acad_blno_badminton"]["status"] == "done"
    assert docs["broken"]["status"] == "failed"
