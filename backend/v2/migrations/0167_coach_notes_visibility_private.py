"""Backfill ``visibility: "private"`` on every existing coach note.

Coach notes gain an audience flag (spec
``2026-09-04-role-model-and-screens-design.md``, item 6): ``private`` stays
with coaches and supervisors, ``shared`` is visible to the student's parent.
The locked "default to private" decision is applied to history too: every
``progress_notes`` and ``coach_skill_notes`` document that predates the flag
is stamped ``private``. Parents who could see a progress note before this
migration stop seeing it until its coach (or an owner/admin) shares it again.

The application already treats a missing field as private, so this backfill
is not load-bearing for correctness; it makes the parent feed's equality
match (``visibility == "shared"``) exact and lets future indexes/validators
assume the field exists. Idempotent: only documents without the field are
touched, and a second run modifies nothing.

Validators: migration 0133's ``coach_skill_notes`` ``$jsonSchema`` lists
properties without ``additionalProperties: false``, so the new field passes
without widening; ``progress_notes`` has no validator at all.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
#629); apply it by hand right after the deploy that ships the flag, via
``fly ssh console -a courtmastr-academy-api`` and
``backend.v2.migrations.run_pending_migrations`` (same as 0165/0166), and
report the two modified counts it logs.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger(__name__)

version = "0167_coach_notes_visibility_private"

COLLECTIONS = ("progress_notes", "coach_skill_notes")


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    for name in COLLECTIONS:
        result = await db[name].update_many(
            {"visibility": {"$exists": False}},
            {"$set": {"visibility": "private"}},
        )
        log.info(
            "0167: %s — stamped visibility=private on %d note(s) (matched %d)",
            name,
            result.modified_count,
            result.matched_count,
        )
