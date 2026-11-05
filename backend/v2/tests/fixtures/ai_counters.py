"""In-memory ``AiCallCounterRepository`` for AI feature tests.

Mirrors ``MongoAiCallCounterRepository`` (pinned on a real ``mongod`` in
``tests/contract/test_ai_calls_real_mongo.py``): one count per key, ``reserve``
takes a slot only while the count is under the cap (a cap of 0 or less always
refuses), ``release`` never goes below zero. Keys carry their own period, so a
new month or day starts at zero."""

from __future__ import annotations

from datetime import UTC, datetime


class InMemoryAiCallCounters:
    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.counts: dict[str, int] = dict(counts or {})

    async def reserve(self, key: str, cap: int) -> bool:
        if cap <= 0 or self.counts.get(key, 0) >= cap:
            return False
        self.counts[key] = self.counts.get(key, 0) + 1
        return True

    async def release(self, key: str) -> None:
        if self.counts.get(key, 0) > 0:
            self.counts[key] -= 1


def counters_at(used: int = 0, now: datetime | None = None) -> InMemoryAiCallCounters:
    """Counters with ``used`` slots already taken in ``now``'s UTC month."""
    now = now or datetime.now(UTC)
    return InMemoryAiCallCounters({f"month:{now:%Y-%m}": used} if used else {})
