"""Contract tests for the boot-migrations distributed lock (issue #507).

Concurrency is modelled sequentially, exactly as ``test_job_lease.py`` does:
a second runner started while another machine holds the lease. ``gather``
over mongomock-motor cannot stand in for real single-document atomicity.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.v2.migrations import runner
from backend.v2.shared.scheduling.lease import COLLECTION as LEASE_COLLECTION
from backend.v2.shared.scheduling.lease import job_lease

TTL = timedelta(minutes=15)


def _stub_migration(calls: list[str], version: str = "9001_stub"):
    async def up(db) -> None:
        calls.append(version)

    return SimpleNamespace(version=version, up=up)


@pytest.mark.asyncio
async def test_runner_waits_while_another_machine_holds_the_lease(db, monkeypatch) -> None:
    """A boot that loses the lease race must not run migrations concurrently.

    Fails without the fix: the old runner had no lock, so it would apply the
    stub migration immediately even though another machine holds the lease.
    """
    calls: list[str] = []
    monkeypatch.setattr(runner, "_discover_migrations", lambda: [_stub_migration(calls)])

    async with job_lease(db, runner.MIGRATIONS_LEASE_NAME, TTL, "other-machine") as held:
        assert held is True
        task = asyncio.create_task(
            runner.run_pending_migrations(db, worker_id="this-machine", poll_interval=0.01)
        )
        # Give the loser several poll cycles while the lease is held.
        await asyncio.sleep(0.05)
        assert calls == [], "runner must not apply migrations while lease is held elsewhere"
        assert not task.done()
        # Simulate the holder finishing its run: record the version, then the
        # context manager releases the lease on exit.
        await runner._record_applied(db, "9001_stub")

    applied = await asyncio.wait_for(task, timeout=5)
    assert applied == []  # the other machine already applied it
    assert calls == []
    count = await db[runner.REGISTRY_COLLECTION].count_documents({"version": "9001_stub"})
    assert count == 1


@pytest.mark.asyncio
async def test_runner_applies_after_stale_lease_expires(db, monkeypatch) -> None:
    """A crashed holder's expired lease must not block boot forever."""
    calls: list[str] = []
    monkeypatch.setattr(runner, "_discover_migrations", lambda: [_stub_migration(calls)])

    now = datetime.now(UTC)
    await db[LEASE_COLLECTION].insert_one(
        {
            "_id": runner.MIGRATIONS_LEASE_NAME,
            "locked_until": now - timedelta(minutes=1),
            "lock_owner": "crashed-machine",
            "updated_at": now - timedelta(minutes=20),
        }
    )

    applied = await asyncio.wait_for(
        runner.run_pending_migrations(db, worker_id="this-machine", poll_interval=0.01),
        timeout=5,
    )
    assert applied == ["9001_stub"]
    assert calls == ["9001_stub"]


@pytest.mark.asyncio
async def test_lost_race_recording_is_a_noop_not_a_duplicate(db, monkeypatch) -> None:
    """With the unique index in place, recording an already-recorded version
    must be an upsert no-op.

    Fails without the fix: the old ``insert_one`` either raised
    DuplicateKeyError (index present) or wrote a duplicate row (no index).
    """
    mod = importlib.import_module("backend.v2.migrations.0156_migrations_registry_unique_index")
    await mod.up(db)

    calls: list[str] = []
    version = "9002_race"

    async def up(inner_db) -> None:
        calls.append(version)
        # Simulate the other machine winning mid-flight: it records the
        # version between our applied-set read and our own recording.
        await inner_db[runner.REGISTRY_COLLECTION].insert_one(
            {"version": version, "applied_at": datetime.now(UTC)}
        )

    monkeypatch.setattr(
        runner, "_discover_migrations", lambda: [SimpleNamespace(version=version, up=up)]
    )

    applied = await asyncio.wait_for(
        runner.run_pending_migrations(db, worker_id="this-machine", poll_interval=0.01),
        timeout=5,
    )
    assert applied == [version]
    count = await db[runner.REGISTRY_COLLECTION].count_documents({"version": version})
    assert count == 1


@pytest.mark.asyncio
async def test_0156_dedupes_historical_duplicate_rows(db) -> None:
    mod = importlib.import_module("backend.v2.migrations.0156_migrations_registry_unique_index")
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 2, 1, tzinfo=UTC)
    await db[runner.REGISTRY_COLLECTION].insert_many(
        [
            {"version": "0001_x", "applied_at": late},
            {"version": "0001_x", "applied_at": early},
            {"version": "0002_y", "applied_at": early},
        ]
    )

    await mod.up(db)

    docs = [doc async for doc in db[runner.REGISTRY_COLLECTION].find({"version": "0001_x"})]
    assert len(docs) == 1
    # Mongo stores naive UTC datetimes.
    assert docs[0]["applied_at"].replace(tzinfo=None) == early.replace(tzinfo=None)
    assert await db[runner.REGISTRY_COLLECTION].count_documents({}) == 2
