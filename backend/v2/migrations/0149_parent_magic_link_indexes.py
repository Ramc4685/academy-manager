"""Indexes for the ``parent_magic_links`` collection (parent magic-link login).

* ``token_hash`` unique — the lookup key for ``get_by_hash`` and the guard
  against two rows sharing a hash.
* ``purge_at`` TTL (``expireAfterSeconds=0``) — Mongo deletes a row once
  ``purge_at`` passes, so consumed/expired tokens self-clean after the 7-day
  grace window without an app-side sweep.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0149"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    links = db["parent_magic_links"]
    await links.create_index(
        "token_hash",
        unique=True,
        name="parent_magic_links_token_hash_unique",
    )
    await links.create_index(
        "purge_at",
        expireAfterSeconds=0,
        name="parent_magic_links_purge_at_ttl",
    )
