"""Claim semantics for in-memory ``IdempotencyStore`` fakes.

Mirrors ``MongoIdempotencyStore.claim``: the first caller takes a key, every
later caller is refused until ``release``.
"""

from __future__ import annotations


class ClaimableStore:
    async def claim(self, key: str) -> bool:
        claimed: set[str] = self.__dict__.setdefault("_claimed", set())
        if key in claimed:
            return False
        claimed.add(key)
        return True

    async def release(self, key: str) -> None:
        self.__dict__.setdefault("_claimed", set()).discard(key)
