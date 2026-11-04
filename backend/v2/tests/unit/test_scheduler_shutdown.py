"""Graceful scheduler drain at shutdown (issue #752).

APScheduler's ``AsyncIOExecutor.shutdown`` ignores its ``wait`` argument — it
cancels every pending future unconditionally — so ``shutdown(wait=True)`` buys
nothing for asyncio jobs. Draining explicitly before shutdown is what actually
lets an in-flight job finish while Fly is replacing the machine.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.v2.main import _drain_scheduler


class _FakeExecutor:
    def __init__(self, pending: set[Any]) -> None:
        self._pending_futures = pending


class _FakeScheduler:
    def __init__(self, pending: set[Any]) -> None:
        self._executors = {"default": _FakeExecutor(pending)}
        self.paused = False

    def pause(self) -> None:
        self.paused = True


@pytest.mark.asyncio
async def test_drain_waits_for_an_in_flight_job_to_finish() -> None:
    finished: list[str] = []

    async def job() -> None:
        await asyncio.sleep(0.01)
        finished.append("done")

    task = asyncio.ensure_future(job())
    scheduler = _FakeScheduler({task})

    await _drain_scheduler(scheduler, drain_seconds=5.0)

    assert finished == ["done"]
    assert task.done() and not task.cancelled()
    # Paused first so no new tick starts while we wait.
    assert scheduler.paused is True


@pytest.mark.asyncio
async def test_drain_is_bounded_and_leaves_a_slow_job_to_the_shutdown() -> None:
    async def forever() -> None:
        await asyncio.sleep(60)

    task = asyncio.ensure_future(forever())
    scheduler = _FakeScheduler({task})

    await _drain_scheduler(scheduler, drain_seconds=0.01)

    assert not task.done()
    task.cancel()


@pytest.mark.asyncio
async def test_drain_never_raises_when_the_scheduler_misbehaves() -> None:
    class _Exploding:
        def pause(self) -> None:
            raise RuntimeError("scheduler not running")

    await _drain_scheduler(_Exploding(), drain_seconds=0.01)
