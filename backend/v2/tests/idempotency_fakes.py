"""Claim semantics for in-memory ``IdempotencyStore`` fakes.

Mirrors ``MongoIdempotencyStore.claim``: the first caller takes a key and gets a
token, every later caller is refused until ``release`` with that token.
"""

from __future__ import annotations


class ClaimableStore:
    async def claim(self, key: str, *, takeover: bool = True) -> object | None:
        claimed: dict[str, object] = self.__dict__.setdefault("_claimed", {})
        if key in claimed:
            return None
        token = claimed[key] = object()
        return token

    async def release(self, key: str, token: object) -> None:
        claimed: dict[str, object] = self.__dict__.setdefault("_claimed", {})
        if claimed.get(key) is token:
            del claimed[key]
