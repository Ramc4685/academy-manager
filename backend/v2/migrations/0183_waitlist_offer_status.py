"""Waitlist offer window: ``offered``/``expired`` + ``offer_expires_at`` (#828).

A freed seat is no longer handed to the next family the instant it opens.
``PromoteFromWaitlist`` now holds the seat and marks the entry ``offered``
with ``offer_expires_at = now + 3 days``; the family confirms through the
parent BFF (``offered`` -> ``promoted``), and ``SweepExpiredWaitlistOffers``
releases the seat and marks the entry ``expired`` when the window closes.

Migration 0133 pins ``waitlist.status`` to the four pre-#828 values, so both
new statuses would be rejected with "Document failed validation" and the
deadline field would be untyped. 0133's definition is corrected in place
(single source of truth, the same way 0165/0169/0182 do it) and re-applied
here.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
#629); apply it by hand right after the deploy via ``fly ssh console -a
courtmastr-academy-api`` and ``backend.v2.migrations.run_pending_migrations``.
Until it is applied, a freed seat simply fails to be offered — the write that
is rejected is the ``mark_offered`` update, which happens AFTER the seat is
reserved, so the sweep's release plus the next promotion attempt recover the
seat rather than leaking it.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger(__name__)

version = "0183_waitlist_offer_status"

COLLECTION = "waitlist"


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    base = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    validator = base.VALIDATORS[COLLECTION]
    schema = validator["$jsonSchema"]
    status_enum = schema["properties"]["status"]["enum"]
    assert "offered" in status_enum and "expired" in status_enum, (
        "0133 must list the #828 waitlist statuses"
    )
    assert "offer_expires_at" in schema["properties"], "0133 must type offer_expires_at"
    await base._apply_validator(db, COLLECTION, validator)
    log.info("0183: %s validator re-applied with the offer statuses", COLLECTION)
