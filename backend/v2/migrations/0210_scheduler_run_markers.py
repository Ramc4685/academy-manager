"""Indexes for ``scheduler_run_markers``, the once-per-academy-local-day claim
for the scheduled daily jobs (Settings overhaul Phase 4, HARDCODED #8).

Each hourly tick of a daily job claims ``(job, academy_id, local_date)`` before
running it for that academy (``shared/scheduling/local_clock.py``). Two indexes:

* ``scheduler_run_markers_academy_job_date_unique``: ``(academy_id, job,
  local_date)``, unique. The claim does NOT depend on it: the marker ``_id``
  is the same triple, so the always-present ``_id`` index already makes the
  insert atomic. This one states the invariant and serves the per-academy
  reads (#849: tenant indexes lead with ``academy_id``).
* ``scheduler_run_markers_created_ttl``: TTL on ``created_at``, 60 days. A
  marker only matters on its own local date; 60 days keeps enough history to
  answer "did the 03:00 run happen for academy X on day Y" in an incident.

No partial filter; nothing queries it with ``$or`` across indexed fields.
New, empty collection: no data is read or changed. Idempotent:
``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0210_scheduler_run_markers"

TTL_SECONDS = 60 * 24 * 60 * 60

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "scheduler_run_markers",
        "scheduler_run_markers_academy_job_date_unique",
        [("academy_id", 1), ("job", 1), ("local_date", 1)],
        {"unique": True},
    ),
    (
        "scheduler_run_markers",
        "scheduler_run_markers_created_ttl",
        [("created_at", 1)],
        {"expireAfterSeconds": TTL_SECONDS},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
