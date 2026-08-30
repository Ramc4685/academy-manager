"""Small in-process TTL cache for the hot per-request auth path (issue #527).

Deliberately minimal: a dict of ``key -> (expires_at, value)`` using a
monotonic clock. Single-process, single-event-loop semantics — no locking is
needed because entries are read and written between awaits, never across
threads. Not a general-purpose cache: entries are opaque to invalidation, so
only use it for data that is safe to be up to ``ttl`` seconds stale.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class TTLCache[V]:
    """Bounded TTL cache. Expired entries are dropped lazily on access.

    ``max_size`` bounds memory: when full, the oldest-inserted entry is
    evicted (dict preserves insertion order — close enough to FIFO for a
    short-TTL cache where entries all expire within a minute anyway).
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_size: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._clock = clock
        self._entries: dict[str, tuple[float, V]] = {}

    def get(self, key: str) -> V | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: V, *, ttl_seconds: float | None = None) -> None:
        """Store ``value``; ``ttl_seconds`` overrides the default per entry.

        A non-positive override means "already stale" and is not stored.
        """
        ttl = self._ttl if ttl_seconds is None else min(ttl_seconds, self._ttl)
        if ttl <= 0:
            return
        now = self._clock()
        if key not in self._entries and len(self._entries) >= self._max_size:
            self._evict_one(now)
        # Re-insert so insertion order tracks recency of writes.
        self._entries.pop(key, None)
        self._entries[key] = (now + ttl, value)

    def _evict_one(self, now: float) -> None:
        # Prefer dropping an already-expired entry; else drop the oldest.
        for key, (expires_at, _) in self._entries.items():
            if now >= expires_at:
                self._entries.pop(key, None)
                return
        oldest = next(iter(self._entries), None)
        if oldest is not None:
            self._entries.pop(oldest, None)

    def __len__(self) -> int:
        return len(self._entries)
