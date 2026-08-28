"""Unit tests for the real /healthz report (issue #429)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.shared.observability.health import build_health_report

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

#: The exact pattern scripts/smoke/production_smoke.sh greps the raw body for.
SMOKE_PATTERN = re.compile(r'"status"\s*:\s*"ok"')


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def __aiter__(self):
        async def _gen():
            for doc in self._docs:
                yield doc

        return _gen()


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def find(self, *_args, **_kwargs) -> _FakeCursor:
        return _FakeCursor(self._docs)


class _FakeDb:
    def __init__(
        self,
        *,
        ping: Any = "ok",
        job_docs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ping = ping
        self._collections = {"ops_job_runs": _FakeCollection(job_docs or [])}

    async def command(self, name: str) -> dict[str, int]:
        assert name == "ping"
        if isinstance(self._ping, Exception):
            raise self._ping
        if self._ping == "hang":
            await asyncio.sleep(30)
        return {"ok": 1}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.get(name, _FakeCollection([]))


class _FakeScheduler:
    def __init__(self, *, running: bool = True, jobs: int = 7) -> None:
        self.running = running
        self._jobs = jobs

    def get_jobs(self) -> list[object]:
        return [object()] * self._jobs


class _FakeDispatcher:
    def __init__(self, *, running: bool = True) -> None:
        self._running = running

    def is_running(self) -> bool:
        return self._running


@pytest.mark.asyncio
async def test_all_components_healthy_reports_ok() -> None:
    report, healthy = await build_health_report(
        db=_FakeDb(), scheduler=_FakeScheduler(), dispatcher=_FakeDispatcher(), now=NOW
    )

    assert healthy is True
    assert report["status"] == "ok"
    assert report["checks"]["mongo"]["ok"] is True
    assert report["checks"]["scheduler"] == {"ok": True, "jobs": 7}
    assert report["checks"]["dispatcher"] == {"ok": True}


@pytest.mark.asyncio
async def test_a_lost_mongo_connection_is_unhealthy() -> None:
    report, healthy = await build_health_report(
        db=_FakeDb(ping=RuntimeError("connection lost")),
        scheduler=_FakeScheduler(),
        dispatcher=_FakeDispatcher(),
        now=NOW,
    )

    assert healthy is False
    assert report["status"] == "degraded"
    assert report["checks"]["mongo"]["ok"] is False


@pytest.mark.asyncio
async def test_a_hanging_mongo_ping_times_out_inside_flys_budget() -> None:
    """Fly's check times out at 5s. We must answer first, with a reason."""
    report, healthy = await build_health_report(
        db=_FakeDb(ping="hang"),
        scheduler=_FakeScheduler(),
        dispatcher=_FakeDispatcher(),
        now=NOW,
    )

    assert healthy is False
    assert report["checks"]["mongo"] == {"ok": False, "error": "ping timed out"}


@pytest.mark.asyncio
async def test_a_stopped_scheduler_is_unhealthy() -> None:
    report, healthy = await build_health_report(
        db=_FakeDb(),
        scheduler=_FakeScheduler(running=False),
        dispatcher=_FakeDispatcher(),
        now=NOW,
    )

    assert healthy is False
    assert report["checks"]["scheduler"]["ok"] is False


@pytest.mark.asyncio
async def test_a_dead_dispatcher_task_is_unhealthy() -> None:
    """A stopped dispatcher leaves every appended event in the outbox forever
    while the process happily serves traffic."""
    report, healthy = await build_health_report(
        db=_FakeDb(),
        scheduler=_FakeScheduler(),
        dispatcher=_FakeDispatcher(running=False),
        now=NOW,
    )

    assert healthy is False
    assert report["checks"]["dispatcher"]["ok"] is False


@pytest.mark.asyncio
async def test_components_that_were_never_wired_do_not_fail_the_check() -> None:
    """A restart cannot wire a component that was never assembled, so failing
    here would only produce a boot loop."""
    report, healthy = await build_health_report(now=NOW)

    assert healthy is True
    assert report["status"] == "ok"
    assert all(check["skipped"] == "not wired" for check in report["checks"].values())


@pytest.mark.asyncio
async def test_a_stale_job_heartbeat_is_reported_but_stays_healthy() -> None:
    """Restarting the machine will not make an overdue monthly job run, so a
    stale heartbeat must not flap the Fly health check."""
    db = _FakeDb(
        job_docs=[
            {
                "_id": "generate_monthly_invoices",
                "last_tick_at": NOW - timedelta(days=30),
                "recorded_at": NOW - timedelta(days=30),
            }
        ]
    )

    report, healthy = await build_health_report(
        db=db, scheduler=_FakeScheduler(), dispatcher=_FakeDispatcher(), now=NOW
    )

    assert healthy is True
    assert report["jobs"]["generate_monthly_invoices"]["last_tick_age_seconds"] == 2_592_000


@pytest.mark.asyncio
async def test_naive_mongo_timestamps_do_not_break_the_endpoint() -> None:
    db = _FakeDb(job_docs=[{"_id": "send_ops_digest", "last_tick_at": NOW.replace(tzinfo=None)}])

    report, healthy = await build_health_report(db=db, now=NOW)

    assert healthy is True
    assert report["jobs"]["send_ops_digest"] == {
        "last_tick_age_seconds": 0,
        "last_run_age_seconds": None,
    }


@pytest.mark.asyncio
async def test_a_degraded_body_cannot_pass_the_production_smoke_check() -> None:
    """The deploy smoke script greps the raw body for `"status":"ok"`. If a
    nested per-check result ever used a `status` key, a degraded API would
    pass the post-deploy smoke test and the outage would ship."""
    report, healthy = await build_health_report(
        db=_FakeDb(ping=RuntimeError("down")),
        scheduler=_FakeScheduler(),
        dispatcher=_FakeDispatcher(),
        now=NOW,
    )

    assert healthy is False
    # Both spacings the script's pattern tolerates.
    assert not SMOKE_PATTERN.search(json.dumps(report))
    assert not SMOKE_PATTERN.search(json.dumps(report, separators=(",", ":")))


@pytest.mark.asyncio
async def test_a_healthy_body_still_passes_the_production_smoke_check() -> None:
    report, _ = await build_health_report(
        db=_FakeDb(), scheduler=_FakeScheduler(), dispatcher=_FakeDispatcher(), now=NOW
    )

    assert SMOKE_PATTERN.search(json.dumps(report))
    assert SMOKE_PATTERN.search(json.dumps(report, separators=(",", ":")))


@pytest.mark.asyncio
async def test_heartbeats_are_not_read_when_mongo_is_down() -> None:
    """Against a dead Mongo this read would block on the driver's
    server-selection timeout — six times Fly's 5s check budget — turning a
    clean 503 into a hung request Fly can only score as a timeout."""

    class _ExplodingCollection:
        def find(self, *_args, **_kwargs):
            raise AssertionError("heartbeats must not be read once the ping failed")

    db = _FakeDb(ping=RuntimeError("down"))
    db._collections["ops_job_runs"] = _ExplodingCollection()

    report, healthy = await build_health_report(db=db, now=NOW)

    assert healthy is False
    assert "jobs" not in report
