"""Tests for the @idempotent decorator with an in-memory store."""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.shared.idempotency import idempotent
from backend.v2.tests.idempotency_fakes import ClaimableStore


class InMemoryStore(ClaimableStore):
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = value


class _UseCase:
    def __init__(self) -> None:
        self._idempotency_store = InMemoryStore()
        self.calls = 0

    @idempotent(key_from=lambda self, k: f"uc:{k}")
    async def run(self, k: str) -> dict[str, Any]:
        self.calls += 1
        return {"result": k.upper(), "calls": self.calls}


@pytest.mark.asyncio
async def test_idempotent_runs_once_per_key() -> None:
    uc = _UseCase()
    a = await uc.run("hello")
    b = await uc.run("hello")
    c = await uc.run("world")

    assert a == b
    assert a["result"] == "HELLO"
    assert c["result"] == "WORLD"
    assert uc.calls == 2  # "hello" cached, "world" ran fresh


@pytest.mark.asyncio
async def test_idempotent_requires_store_attribute() -> None:
    class Bare:
        @idempotent(key_from=lambda self, k: k)
        async def run(self, k: str) -> str:
            return k

    with pytest.raises(RuntimeError, match="IdempotencyStore"):
        await Bare().run("x")


@pytest.mark.asyncio
async def test_a_failed_result_write_frees_the_key_for_a_retry() -> None:
    class _PutFailsOnce(InMemoryStore):
        failed = False

        async def put(self, key: str, value: dict[str, Any]) -> None:
            if not self.failed:
                self.failed = True
                raise ConnectionError("lost the write")
            await super().put(key, value)

    uc = _UseCase()
    uc._idempotency_store = _PutFailsOnce()
    with pytest.raises(ConnectionError):
        await uc.run("hello")

    assert (await uc.run("hello"))["calls"] == 2  # retried, not 409 in-flight
