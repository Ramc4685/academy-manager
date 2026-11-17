"""Contract tests for MongoIdempotencyStore + the @idempotent decorator.

The decorator (unit-tested against an in-memory fake) and the production Mongo
store must agree on the get/put contract: ``get(key)`` returns exactly the value
that ``put(key, value)`` stored. A cache hit must replay the cached result, not
crash.
"""

from __future__ import annotations

import pytest

from backend.v2.shared.idempotency import idempotent
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore


class _CountingUseCase:
    def __init__(self, store: MongoIdempotencyStore) -> None:
        self._idempotency_store = store
        self.calls = 0

    @idempotent(key_from=lambda self, k: f"uc:{k}")
    async def run(self, k: str) -> dict[str, object]:
        self.calls += 1
        return {"result": k.upper(), "calls": self.calls}


@pytest.mark.asyncio
async def test_decorator_cache_hit_replays_through_mongo_store(db) -> None:
    uc = _CountingUseCase(MongoIdempotencyStore(db))

    first = await uc.run("hello")
    # Second call with the same key must replay the cached result rather than
    # raising — the bug was MongoIdempotencyStore.get() returning the whole
    # wrapper document, so the decorator deserialized the wrong shape.
    second = await uc.run("hello")

    assert first == second
    assert first["result"] == "HELLO"
    assert uc.calls == 1  # wrapped body ran once; the replay was served from cache


@pytest.mark.asyncio
async def test_store_get_returns_exactly_what_put_stored(db) -> None:
    store = MongoIdempotencyStore(db)
    payload = {
        "value": {"_type": "raw", "data": {"a": 1}},
        "stored_at": "2026-06-29T00:00:00+00:00",
    }

    await store.put("k1", payload)
    got = await store.get("k1")

    assert got == payload
    assert await store.get("missing") is None


class _SlowUseCase(_CountingUseCase):
    @idempotent(key_from=lambda self, k: f"slow:{k}")
    async def run(self, k: str) -> dict[str, object]:
        import asyncio

        self.calls += 1
        await asyncio.sleep(0.05)  # both first calls are in flight at once
        return {"result": k.upper()}


@pytest.mark.asyncio
async def test_two_concurrent_first_calls_run_the_body_once(real_db) -> None:
    """A read-then-write let both concurrent first calls through: both saw no
    cached result and both ran. The claim is an atomic insert, so one runs and
    the other is refused as in flight."""
    import asyncio

    from backend.v2.shared.idempotency import IdempotentRequestInFlight

    uc = _SlowUseCase(MongoIdempotencyStore(real_db))

    results = await asyncio.gather(uc.run("x"), uc.run("x"), return_exceptions=True)

    assert uc.calls == 1
    # The loser is refused as in flight, or (on a slow machine) replays the stored result.
    assert all(isinstance(r, IdempotentRequestInFlight) or r == {"result": "X"} for r in results)
    assert await uc.run("x") == {"result": "X"}  # later calls replay
    assert uc.calls == 1


@pytest.mark.asyncio
async def test_a_failed_call_releases_its_claim_so_a_retry_runs(real_db) -> None:
    class _FailsOnce(_CountingUseCase):
        @idempotent(key_from=lambda self, k: f"fails:{k}")
        async def run(self, k: str) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return {"result": k}

    uc = _FailsOnce(MongoIdempotencyStore(real_db))
    with pytest.raises(RuntimeError):
        await uc.run("y")
    assert await uc.run("y") == {"result": "y"}


@pytest.mark.asyncio
async def test_a_stale_claim_from_a_dead_request_is_taken_over(real_db) -> None:
    from datetime import UTC, datetime, timedelta

    store = MongoIdempotencyStore(real_db)
    assert await store.claim("k:claim")
    assert not await store.claim("k:claim")
    await real_db["idempotency_keys"].update_one(
        {"key": "k:claim"}, {"$set": {"claimed_at": datetime.now(UTC) - timedelta(minutes=6)}}
    )
    assert await store.claim("k:claim")
    assert not await store.claim("k:claim")


@pytest.mark.asyncio
async def test_a_claim_without_takeover_stays_held_when_stale(real_db) -> None:
    from datetime import UTC, datetime, timedelta

    store = MongoIdempotencyStore(real_db)
    assert await store.claim("nt:claim", takeover=False)
    await real_db["idempotency_keys"].update_one(
        {"key": "nt:claim"}, {"$set": {"claimed_at": datetime.now(UTC) - timedelta(days=1)}}
    )
    assert await store.claim("nt:claim", takeover=False) is None


@pytest.mark.asyncio
async def test_a_taken_over_request_cannot_release_the_new_holders_claim(real_db) -> None:
    from datetime import UTC, datetime, timedelta

    store = MongoIdempotencyStore(real_db)
    first = await store.claim("own:claim")
    await real_db["idempotency_keys"].update_one(
        {"key": "own:claim"}, {"$set": {"claimed_at": datetime.now(UTC) - timedelta(minutes=6)}}
    )
    second = await store.claim("own:claim")  # the stale claim is taken over
    assert second is not None

    await store.release("own:claim", first)  # the dead request wakes up and fails
    assert await store.claim("own:claim") is None  # still held by the second request
    await store.release("own:claim", second)
    assert await store.claim("own:claim") is not None


@pytest.mark.asyncio
async def test_a_duplicate_result_write_replays_the_stored_result(real_db) -> None:
    store = MongoIdempotencyStore(real_db)

    class _Overtaken(_CountingUseCase):
        @idempotent(key_from=lambda self, k: f"dup:{k}")
        async def run(self, k: str) -> dict[str, object]:
            self.calls += 1
            # A request that took over our stale claim stored its result first.
            await store.put(
                f"dup:{k}",
                {"value": {"_type": "raw", "data": {"result": "theirs"}}, "stored_at": "x"},
            )
            return {"result": "ours"}

    assert await _Overtaken(store).run("z") == {"result": "theirs"}
