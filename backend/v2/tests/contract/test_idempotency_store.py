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
