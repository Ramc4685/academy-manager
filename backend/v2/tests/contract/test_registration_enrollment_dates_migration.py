"""Regression coverage for registration-created enrollment timestamps."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from backend.v2.migrations import runner


@pytest.mark.asyncio
async def test_backfills_registration_date_from_onboarding_application(db) -> None:
    module_name = "backend.v2.migrations.0146_registration_enrollment_dates"
    discovered = {module.__name__ for module in runner._discover_migrations()}
    assert module_name in discovered
    migration = importlib.import_module(module_name)

    registered_at = datetime(2026, 7, 9, 15, 30, tzinfo=UTC)
    await db["onboarding_applications"].insert_one(
        {
            "academy_id": "academy-a",
            "application_id": "app-1",
            "enrollment_id": "enrollment-1",
            "status": "APPROVED",
            "created_at": registered_at,
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": "academy-a",
            "enrollment_id": "enrollment-1",
            "student_id": "student-1",
            "session_id": "session-1",
            "status": "active",
        }
    )

    await migration.up(db)

    enrollment = await db["enrollments"].find_one({"enrollment_id": "enrollment-1"})
    assert enrollment is not None
    assert enrollment["enrolled_at"].replace(tzinfo=UTC) == registered_at


@pytest.mark.asyncio
async def test_backfill_preserves_existing_enrollment_date(db) -> None:
    module_name = "backend.v2.migrations.0146_registration_enrollment_dates"
    discovered = {module.__name__ for module in runner._discover_migrations()}
    assert module_name in discovered
    migration = importlib.import_module(module_name)

    original = datetime(2026, 6, 1, tzinfo=UTC)
    await db["onboarding_applications"].insert_one(
        {
            "academy_id": "academy-a",
            "application_id": "app-2",
            "enrollment_id": "enrollment-2",
            "status": "APPROVED",
            "created_at": datetime(2026, 7, 1, tzinfo=UTC),
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": "academy-a",
            "enrollment_id": "enrollment-2",
            "student_id": "student-2",
            "session_id": "session-1",
            "status": "active",
            "enrolled_at": original,
        }
    )

    await migration.up(db)

    enrollment = await db["enrollments"].find_one({"enrollment_id": "enrollment-2"})
    assert enrollment is not None
    assert enrollment["enrolled_at"].replace(tzinfo=UTC) == original
