"""Indexes for CSV import batches (roadmap L8a, ``import_batches``).

``POST /admin/imports/families/preview`` stores one document per uploaded
file: the planned rows, the ids minted for them and the batch status
(``previewed`` -> ``committing`` -> ``committed``). The commit finds the
batch by ``(academy_id, import_batch_id)`` and moves its status with
conditional updates on the same key.

* ``import_batches_academy_batch_unique``: unique ``(academy_id,
  import_batch_id)``. Leads with ``academy_id`` (#849), so a batch id is
  only ever found in its own academy. Not partial: every document carries
  a non-empty ``import_batch_id``.
* ``import_batches_academy_created``: ``(academy_id, created_at desc)`` for
  listing an academy's recent imports.

No ``$jsonSchema`` validator yet (the upload page, L8b, may still add
fields). New collection, so both builds are instant. Idempotent:
``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0199_import_batches"

#: (collection, name, keys, options). Exposed so the unit test pins the shapes.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "import_batches",
        "import_batches_academy_batch_unique",
        [("academy_id", 1), ("import_batch_id", 1)],
        {"unique": True},
    ),
    (
        "import_batches",
        "import_batches_academy_created",
        [("academy_id", 1), ("created_at", -1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
