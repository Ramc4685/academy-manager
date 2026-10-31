"""Widen the registration student lock to every non-ended status (#836).

Migration 0147 built ``uq_registration_active_student_lock`` — the database
backstop that stops two concurrent registration approvals enrolling one child
twice — with ``status ∈ {active, paused}``. That literal predates ``held``
(#697). Issue #782 widened the *application* checks
(``has_active_enrollment``, the approval pre-check) to the domain's
``NON_TERMINAL``; the index was left behind, so a child on hold is invisible
to the one guard that still works when two approvals race.

The filter is rebuilt from ``NON_TERMINAL`` so it reads the same set the code
does. MongoDB cannot alter a partial filter in place, and two indexes on one
key pattern is not portable across server versions, so this is drop-then-
create under the same name. The gap between the two is milliseconds and the
application pre-checks stay in force throughout; what would NOT be acceptable
is dropping and then failing to create, so a pre-flight names any existing
collision and aborts with the old index untouched. Production had zero
``held`` rows when this was written (2026-09-20).

Idempotent: an index that already carries the wide filter is left alone.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
#629); apply it by hand right after the deploy via ``fly ssh console -a
courtmastr-academy-api`` and ``backend.v2.migrations.run_pending_migrations``.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.enrollment.domain.models import NON_TERMINAL

version = "0185_registration_lock_non_terminal"

log = logging.getLogger(__name__)

_INDEX = "uq_registration_active_student_lock"
_STATUSES = sorted(NON_TERMINAL)


async def _colliding_locks(enrollments) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """(academy_id, lock) pairs that would break the widened index."""
    cursor = enrollments.aggregate(
        [
            {
                "$match": {
                    "registration_student_lock": {"$type": "string"},
                    "status": {"$in": _STATUSES},
                }
            },
            {
                "$group": {
                    "_id": {
                        "academy_id": "$academy_id",
                        "lock": "$registration_student_lock",
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]
    )
    return [doc async for doc in cursor]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    enrollments = db["enrollments"]
    existing = (await enrollments.index_information()).get(_INDEX)
    if existing is not None:
        current = (existing.get("partialFilterExpression") or {}).get("status", {}).get("$in", [])
        if set(current) == set(_STATUSES):
            return

    collisions = await _colliding_locks(enrollments)
    if collisions:
        offenders = ", ".join(
            f"{row['_id'].get('academy_id')!r}/{row['_id'].get('lock')!r} x{row['count']}"
            for row in collisions
        )
        raise RuntimeError(
            f"0185 aborted: more than one non-ended enrollment already shares a "
            f"registration_student_lock, so the widened {_INDEX} cannot be built. "
            f"Resolve these first (up to 20 shown): {offenders}. "
            "The existing index has been left in place."
        )

    if existing is not None:
        await enrollments.drop_index(_INDEX)
    await enrollments.create_index(
        [("academy_id", 1), ("registration_student_lock", 1)],
        name=_INDEX,
        unique=True,
        partialFilterExpression={
            "registration_student_lock": {"$type": "string"},
            "status": {"$in": _STATUSES},
        },
    )
    log.info("0185: %s now covers %s", _INDEX, _STATUSES)
