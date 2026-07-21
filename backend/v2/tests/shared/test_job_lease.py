"""Concurrency tests for the distributed scheduler job lease.

Covers the four claim invariants (single winner, TTL reclaim, early release,
exception leaves lease to expire) plus one integration-style check that a
wrapped job body runs exactly once when two ticks overlap.

Concurrency is modelled *sequentially* — a second acquire attempted while the
first lease is still held — exactly as ``test_outbox_retry_lock.py`` does for
the dispatcher. ``asyncio.gather`` over ``mongomock-motor`` does not provide
atomic isolation across interleaved awaits, so it cannot stand in for the
single-document atomicity that real MongoDB (and this lease) rely on. The
nested-hold form asserts the same invariant deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.shared.scheduling.lease import COLLECTION, job_lease

TTL = timedelta(minutes=5)


@pytest.mark.asyncio
async def test_second_acquire_while_held_loses(db) -> None:
    """Two workers contending for one name: exactly one wins."""
    async with job_lease(db, "job", TTL, "worker-a") as first:
        assert first is True
        async with job_lease(db, "job", TTL, "worker-b") as second:
            assert second is False


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimable(db) -> None:
    now = datetime.now(UTC)
    await db[COLLECTION].insert_one(
        {
            "_id": "job",
            "locked_until": now - timedelta(minutes=1),
            "lock_owner": "old-worker",
            "updated_at": now - timedelta(minutes=10),
        }
    )
    async with job_lease(db, "job", TTL, "new-worker") as acquired:
        assert acquired is True
        held = await db[COLLECTION].find_one({"_id": "job"})
        assert held["lock_owner"] == "new-worker"


@pytest.mark.asyncio
async def test_fresh_lease_blocks_second_worker(db) -> None:
    now = datetime.now(UTC)
    await db[COLLECTION].insert_one(
        {
            "_id": "job",
            "locked_until": now + TTL,
            "lock_owner": "holder",
            "updated_at": now,
        }
    )
    async with job_lease(db, "job", TTL, "intruder") as acquired:
        assert acquired is False
    # Holder's lease is untouched.
    held = await db[COLLECTION].find_one({"_id": "job"})
    assert held["lock_owner"] == "holder"


@pytest.mark.asyncio
async def test_clean_exit_releases_early(db) -> None:
    async with job_lease(db, "job", TTL, "worker") as acquired:
        assert acquired is True
    # Released on clean exit: a subsequent worker can immediately reclaim.
    async with job_lease(db, "job", TTL, "next") as reacquired:
        assert reacquired is True
        held = await db[COLLECTION].find_one({"_id": "job"})
        assert held["lock_owner"] == "next"


@pytest.mark.asyncio
async def test_exception_leaves_lease_to_expire(db) -> None:
    with pytest.raises(RuntimeError):
        async with job_lease(db, "job", TTL, "worker") as acquired:
            assert acquired is True
            raise RuntimeError("boom")
    # NOT released early: the lease is still held, so the next tick is blocked
    # until the TTL expires.
    async with job_lease(db, "job", TTL, "next") as reacquired:
        assert reacquired is False
    held = await db[COLLECTION].find_one({"_id": "job"})
    assert held["lock_owner"] == "worker"


@pytest.mark.asyncio
async def test_wrapped_body_runs_once_when_ticks_overlap(db) -> None:
    """Two overlapping ticks of the same job: the body runs exactly once."""
    runs = 0

    async def _tick(worker_id: str) -> None:
        nonlocal runs
        async with job_lease(db, "digest", TTL, worker_id) as acquired:
            if not acquired:
                return
            runs += 1

    async with job_lease(db, "digest", TTL, "machine-1") as acquired:
        assert acquired is True
        runs += 1  # machine-1 runs the body while holding the lease
        # machine-2's tick fires before machine-1 finishes: it must skip.
        await _tick("machine-2")

    assert runs == 1
