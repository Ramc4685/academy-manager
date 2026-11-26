"""Rewrite pre-S48 registration locks to the per-class shape.

S48 (D-24) lets a child register for a second class, so new registration
enrollments carry ``registration_student_lock = "<student_id>|<session_id>"``
and ``uq_registration_active_student_lock`` (0147, widened by 0185) refuses a
second live row for the same child AND class. Rows written before S48 still
hold the bare ``student_id``, which never compares equal to the new shape, so
two racing approvals of an already-enrolled child into the same class would
both pass the index. This rewrites every non-ended old lock to the new shape.

It cannot collide: the old index allowed one live lock per child, so appending
the row's own class keeps every lock unique. Ended rows sit outside the partial
filter and are left alone. Idempotent: rewritten rows contain ``|`` and are
skipped on a re-run.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.enrollment.domain.models import NON_TERMINAL

version = "0249_registration_lock_per_class"

log = logging.getLogger(__name__)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    enrollments = db["enrollments"]
    cursor = enrollments.find(
        {
            "registration_student_lock": {"$type": "string", "$not": {"$regex": r"\|"}},
            "session_id": {"$type": "string"},
            "status": {"$in": sorted(NON_TERMINAL)},
        },
        {"_id": 1, "registration_student_lock": 1, "session_id": 1},
    )
    rewritten = 0
    async for doc in cursor:
        old = doc["registration_student_lock"]
        result = await enrollments.update_one(
            {"_id": doc["_id"], "registration_student_lock": old},
            {"$set": {"registration_student_lock": f"{old}|{doc['session_id']}"}},
        )
        rewritten += result.modified_count
    log.info("0249: rewrote %d registration locks to the per-class shape", rewritten)
