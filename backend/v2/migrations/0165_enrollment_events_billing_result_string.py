"""Re-apply the ``enrollment_events`` validator with ``billing_result`` as string|object|null.

Production incident 2026-09-04 (#657): admin Remove/Withdraw/Pause enrollment
returned 500 with

    pymongo.errors.WriteError: Document failed validation
      billing_result: bsonType ['object','null'] — consideredValue
      'voided=0,autopay=disabled', consideredType 'string'

Migration 0133 declared ``billing_result`` as ``OPT_OBJECT``, but the domain
model (``EnrollmentLifecycleEvent.billing_result: str | None``) and every writer
emit a short string. The validator only bit once 0133 was applied to prod by
hand on 2026-09-02 (boot migrations are off), which is why the failure looked
new. 0133's schema definition is corrected in place (single source of truth);
this migration re-applies it to existing databases.
"""

from __future__ import annotations

import importlib

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0165_enrollment_events_billing_result_string"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    base = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    validator = base.VALIDATORS["enrollment_events"]
    allowed = validator["$jsonSchema"]["properties"]["billing_result"]["bsonType"]
    assert "string" in allowed, "0133 enrollment_events.billing_result must allow string"
    await base._apply_validator(db, "enrollment_events", validator)
