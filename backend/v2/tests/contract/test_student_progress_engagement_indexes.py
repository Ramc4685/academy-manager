"""Contract tests for student-progress engagement indexes."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.asyncio
async def test_student_progress_engagement_migration_adds_window_index(db) -> None:
    migration = importlib.import_module(
        "backend.v2.migrations.0127_student_progress_engagement_indexes"
    )

    await migration.up(db)

    indexes = await db["student_skill_progress"].index_information()
    assert indexes["skill_progress_engagement_window"]["key"] == [
        ("academy_id", 1),
        ("last_updated_at", -1),
        ("last_updated_by", 1),
        ("status", 1),
    ]
