"""Indexes for ``programs`` and the public-class lookup on ``sessions`` (Lane B1).

Public tenant page, piece D. ``programs`` is a new tenant-scoped collection
(the Program entity that groups classes on the public page); the model,
repository and admin use cases live in ``backend/v2/contexts/enrollment``
(``domain/programs.py``). New collection, no data to move: Mongo creates it
on the first ``create_index``.

Per-class public fields (``published``, ``program_id``, ``price_period``,
``coach_display``, ``public_description``, ``level``, ``age_band``) live on
the existing ``sessions`` rows and are all optional: a missing key reads as
its default (``published`` missing == private), so **no backfill** and no
document is touched here. The academy-level ``public_page`` subdocument is
likewise read with defaults and needs nothing.

Every index leads with ``academy_id`` (#849), none is a global unique on an
id, and none is partial (so no ``$type``/``$exists`` filter, #878):

* ``programs_academy_program_unique``: one row per (academy, program_id);
* ``programs_academy_sort``: the admin list and the public page, in order;
* ``sessions_academy_published``: the public read (B2) asks for one
  academy's published classes on every anonymous page view.

Idempotent: ``create_index`` with the same name and spec is a no-op.
Applied only by the migrate job, never by hand.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0194_programs"

#: (collection, name, keys, options). Exposed so the unit test pins the shapes.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "programs",
        "programs_academy_program_unique",
        [("academy_id", 1), ("program_id", 1)],
        {"unique": True},
    ),
    (
        "programs",
        "programs_academy_sort",
        [("academy_id", 1), ("sort_order", 1)],
        {},
    ),
    (
        "sessions",
        "sessions_academy_published",
        [("academy_id", 1), ("published", 1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
