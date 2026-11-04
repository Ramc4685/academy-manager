"""Index ``users.user_id`` and ``users.auth_uid`` for parent alias resolution.

The People CRM family index and the alias-aware Family billing page (People
CRM spec §1, §7 Phase 2) resolve stored parent references with one ``$in``
equality lookup per field, in order ``user_id``, ``firebase_uid``,
``auth_uid``, ``_id`` (``MongoUserRepository.resolve_parent_aliases``), never
an ``$or`` across the fields (the #878/#886 shape MongoDB 8.0 scans, #894).
``explain()`` against a real mongod with every migration applied showed:

* ``firebase_uid`` → ``users_firebase_uid_unique`` (0080), ``_id`` → ``_id_``;
* ``user_id`` and ``auth_uid`` → **COLLSCAN**: no migration ever indexed them.

So this adds exactly those two. ``users`` is the one global identity
collection (a user spans academies), so the keys do not lead with
``academy_id``; they are plain, non-unique and non-partial on purpose:

* non-unique, because legacy rows may share a ``user_id`` or ``auth_uid``
  and a unique build would fail the migration mid-deploy; the resolver picks
  the lowest ``_id`` deterministically when that happens;
* non-partial, so the planner serves both equality and ``$in`` without a
  partial-filter implication check (no ``$type`` filter, #878).

Idempotent, and safe against drift: an index already keyed exactly like one
of these (under any name, e.g. built by hand or by the retired v1 app) is
left alone, because ``create_index`` on the same keys under a new name
raises ``IndexOptionsConflict`` and would fail the deploy. The build reads
``users`` once; the collection is small (one row per person).
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0193_users_parent_alias_lookup_indexes"

COLLECTION = "users"

#: (name, keys, options). Exposed so the unit test pins the exact shapes.
INDEXES: list[tuple[str, list[tuple[str, int]], dict[str, Any]]] = [
    ("users_user_id_lookup", [("user_id", 1)], {}),
    ("users_auth_uid_lookup", [("auth_uid", 1)], {}),
]


def _key_spec(keys: Any) -> tuple[tuple[str, Any], ...]:
    # Index directions come back as 1 or 1.0 depending on the server/driver.
    return tuple((str(field), int(d) if isinstance(d, int | float) else d) for field, d in keys)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    coll = db[COLLECTION]
    existing = await coll.index_information()
    keyed = {_key_spec(spec["key"]) for spec in existing.values()}
    for name, keys, options in INDEXES:
        if name not in existing and _key_spec(keys) in keyed:
            continue  # an equivalent index exists under another name
        await coll.create_index(keys, name=name, **options)
