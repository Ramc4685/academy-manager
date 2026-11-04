"""Drop ``APPROVED`` from the level-up active-recommendation index (#786).

Issue #786: approval never reached a terminal status. The review use case
stamped ``APPROVED`` on approve and never moved a row on from there, so
``APPROVED`` counted as an active recommendation forever — permanently
blocking any further level-up for that student/program. The review use case
now writes ``COMPLETED`` on approve instead (``COMPLETED`` was already a
legal ``$jsonSchema``/``LevelUpStatus`` value, so no validator change is
needed here), and ``ACTIVE_LEVEL_UP_STATUSES`` in
``student_progress/domain/models.py`` no longer includes ``APPROVED``.

That leaves ``recs_active_unique`` (migration 0176) out of step: its partial
filter still lists ``APPROVED``, so a legacy row stuck in that status from
before this fix stays inside the unique index. That is harmless for
uniqueness (the index only gets TOO strict, never silently permissive) but is
worth tidying up so the index matches what the application now means by
"active" — and so a fresh database's index matches production once this runs
there.

Partial-index filters cannot be edited in place, so the index is dropped and
rebuilt, exactly as 0176 did. Safe for the same reason 0176's rebuild was:
the narrowed filter only ever covers FEWER documents than before (drops one
status out of four), so the rebuild cannot collide with an existing row that
was relying on the old, wider filter for uniqueness protection — a row that
already violated uniqueness under the old filter could not exist in the first
place.

No ``down()``: ``runner.py`` has no rollback concept and none of the
migrations here define one.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

log = logging.getLogger(__name__)

version = "0179_level_up_active_index_drops_approved"

COLLECTION = "level_up_recommendations"
ACTIVE_INDEX = "recs_active_unique"

#: Mirrors ``ACTIVE_LEVEL_UP_STATUSES`` in
#: ``student_progress/domain/models.py`` as of issue #786. Spelled out rather
#: than imported, deliberately, for the same reason migration 0176 does:
#: a migration is an append-only record of what was applied, and importing
#: live domain code would let a future vocabulary change retroactively alter
#: what this already-applied migration means.
#: ``test_0179_level_up_active_index_drops_approved.py`` pins this against
#: the live constant so the two cannot silently drift.
ACTIVE_STATUSES = ["APPROVING", "RECOMMENDED", "REJECTING"]

#: MongoDB's "index/collection not found" error codes — a fresh database, or
#: one that has not yet run 0176, has neither.
_INDEX_NOT_FOUND = 27
_NAMESPACE_NOT_FOUND = 26


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    recs = db[COLLECTION]
    try:
        await recs.drop_index(ACTIVE_INDEX)
    except NotImplementedError:
        # mongomock-motor in tests: no partial index enforcement to restore.
        return
    except OperationFailure as exc:
        if exc.code not in (_INDEX_NOT_FOUND, _NAMESPACE_NOT_FOUND):
            raise
    await recs.create_index(
        [("academy_id", 1), ("student_id", 1), ("from_level_id", 1)],
        unique=True,
        name=ACTIVE_INDEX,
        partialFilterExpression={"status": {"$in": ACTIVE_STATUSES}},
    )
