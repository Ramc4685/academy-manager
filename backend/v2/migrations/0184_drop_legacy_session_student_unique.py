"""Drop the legacy unique ``(session_id, student_id)`` index on enrollments.

Production carried an auto-named ``session_id_1_student_id_1`` unique index
that no migration in this repo creates — a leftover from the pre-v2 backend.
It is a FULL unique index (no ``partialFilterExpression``), so it counts ended
rows too: once a student has a ``dropped``/``cancelled`` enrollment in a
class, no new enrollment row for that (session, student) can ever be
inserted.

That contradicts the application rule. ``EditRosterAdd`` only blocks on domain
``LIVE`` statuses — "a cancelled row must not block a re-add" (#642) — so its
pre-check passes, the seat is reserved, and ``enrollments.create`` dies with
E11000. The ``DuplicateKeyError`` arm releases the seat and reports "a
conflicting record already exists for this student", sending the admin to
remove an enrollment that is already gone. Reported 2026-09-20 for a student
dropped on 2026-09-17 and re-added three days later. Registration approval and
waitlist promotion insert through the same collection and hit the same wall.

The index is dropped, not rescoped: "one LIVE enrollment per (session,
student)" is already enforced by the use-case pre-checks, and
``StudentAlreadyOnRoster`` documents that the database is not the enforcer.
Lookups by (session, student) stay covered by ``roster_by_session`` and
``enrollments_for_student`` (migration 0010).

Matched by KEY rather than by name so a hand-built copy under another name is
caught too. Idempotent: a database that never had the index is a no-op.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
#629); apply it by hand right after the deploy via ``fly ssh console -a
courtmastr-academy-api`` and ``backend.v2.migrations.run_pending_migrations``.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0184_drop_legacy_session_student_unique"

log = logging.getLogger(__name__)

_LEGACY_KEY = [("session_id", 1), ("student_id", 1)]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    enrollments = db["enrollments"]
    for name, spec in (await enrollments.index_information()).items():
        key = [(field, int(direction)) for field, direction in spec.get("key", [])]
        if spec.get("unique") and key == _LEGACY_KEY:
            await enrollments.drop_index(name)
            log.info("0184: dropped legacy unique (session_id, student_id) index %s", name)
