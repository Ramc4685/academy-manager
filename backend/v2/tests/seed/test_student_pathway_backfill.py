"""Tests for local/test student pathway placement backfill."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from scripts.dev.backfill_student_pathway_placements import (
    backfill_student_pathway_placements,
)

pytestmark = pytest.mark.asyncio


async def _seed_pathway(db: object, *, academy_id: str = "academy-b") -> None:
    now = datetime.now(UTC)
    await db.skill_programs.insert_one(
        {
            "academy_id": academy_id,
            "program_id": "program-1",
            "sport": "badminton",
            "name": "Badminton Skill Pathway",
            "description": "",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "created_by": "test",
        }
    )
    for sequence in (1, 2):
        level_id = f"level-{sequence}"
        await db.skill_levels.insert_one(
            {
                "academy_id": academy_id,
                "level_id": level_id,
                "program_id": "program-1",
                "sequence": sequence,
                "name": f"Level {sequence}",
                "description": "",
                "completion_rule": "ALL_REQUIRED_SKILLS",
                "points_threshold": None,
                "requires_coach_recommendation": True,
                "requires_admin_approval": False,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "created_by": "test",
            }
        )
        await db.skills.insert_one(
            {
                "academy_id": academy_id,
                "skill_id": f"skill-{sequence}",
                "level_id": level_id,
                "program_id": "program-1",
                "sequence": 1,
                "name": f"Skill {sequence}",
                "description": "",
                "is_required": True,
                "scoring_type": "ATTEMPT_BASED",
                "pass_threshold_pct": 70,
                "coach_override_allowed": False,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "created_by": "test",
            }
        )


async def test_backfill_places_mapped_students_and_is_idempotent() -> None:
    db = AsyncMongoMockClient()["student-pathway-backfill"]
    academy_id = "academy-b"
    await _seed_pathway(db, academy_id=academy_id)
    await db.students.insert_many(
        [
            {
                "academy_id": academy_id,
                "student_id": "student-beginner",
                "status": "active",
                "skill_level": "beginner",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
            {
                "academy_id": academy_id,
                "student_id": "student-unmapped",
                "status": "active",
                "skill_level": "expert",
                "created_at": datetime(2026, 1, 2, tzinfo=UTC),
            },
        ]
    )

    first = await backfill_student_pathway_placements(
        db,
        academy_id=academy_id,
        dry_run=False,
    )

    assert first.placed == 1
    assert first.skipped == 0
    assert first.unmappable == 1
    assert await db.student_level_progress.count_documents({"academy_id": academy_id}) == 1
    assert await db.student_skill_progress.count_documents({"academy_id": academy_id}) == 1

    active = await db.student_level_progress.find_one(
        {"academy_id": academy_id, "student_id": "student-beginner", "status": "active"}
    )
    assert active is not None
    assert active["level_id"] == "level-1"

    second = await backfill_student_pathway_placements(
        db,
        academy_id=academy_id,
        dry_run=False,
    )

    assert second.placed == 0
    assert second.skipped == 1
    assert second.unmappable == 1
    assert await db.student_level_progress.count_documents({"academy_id": academy_id}) == 1
    assert await db.student_skill_progress.count_documents({"academy_id": academy_id}) == 1
