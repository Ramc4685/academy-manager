"""Re-apply the ``enrollment_events`` validator with ``reason_code`` (#775).

Drop and Stop-all-classes now record a structured ``reason_code`` alongside
the free-text ``reason`` so the People directory's Left tab can group
departures by why the family left. The field is declared on 0133's schema
(the single source of truth for this collection's validator); this migration
re-applies that schema to databases created before it existed, exactly as
0165 did for ``billing_result``.

Backfill is deliberately absent: the code is a NEW fact, and inferring one
for historical rows from their free text would invent data the admin never
entered. Old rows read back as ``reason_code: None``.
"""

from __future__ import annotations

import importlib

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0179_enrollment_events_reason_code"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    base = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    validator = base.VALIDATORS["enrollment_events"]
    assert "reason_code" in validator["$jsonSchema"]["properties"], (
        "0133 enrollment_events must declare reason_code"
    )
    await base._apply_validator(db, "enrollment_events", validator)
