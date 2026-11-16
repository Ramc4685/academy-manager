"""The November skill-wipe audit reports what was lost and writes nothing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.scripts.skill_wipe_audit import audit

pytestmark = pytest.mark.asyncio

A = "acad-1"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
BASE = {"program_id": "prog", "level_id": "L1"}


def _skill(skill_id: str, seq: int, **extra: Any) -> dict[str, Any]:
    return {
        **BASE,
        "academy_id": A,
        "skill_id": skill_id,
        "sequence": seq,
        "name": skill_id,
        "created_at": NOW,
        "updated_at": NOW,
        **extra,
    }


def _attempt(student: str, passed: bool, academy: str = A) -> dict[str, Any]:
    return {
        **BASE,
        "academy_id": academy,
        "attempt_id": f"{academy}-{student}",
        "student_id": student,
        "skill_id": "k1",
        "coach_id": "coach",
        "scoring_type": "PASS_FAIL",
        "attempts_count": 1,
        "success_count": int(passed),
        "score": int(passed),
        "passed": passed,
        "tested_at": NOW,
    }


def _skill_row(student: str, skill: str, status: str) -> dict[str, Any]:
    return {
        **BASE,
        "academy_id": A,
        "skill_progress_id": f"{student}-{skill}",
        "student_id": student,
        "skill_id": skill,
        "status": status,
        "last_updated_at": NOW,
        "last_updated_by": "coach",
    }


def _level_row(student: str, status: str) -> dict[str, Any]:
    return {
        **BASE,
        "academy_id": A,
        "progress_id": f"p-{student}",
        "student_id": student,
        "status": status,
    }


async def test_reports_wiped_passes_and_false_completions_without_writing(real_db: Any) -> None:
    await real_db["skills"].insert_many(
        [
            _skill("k1", 1, is_active=True),
            _skill("k2", 2),
            # Optional and retired skills never block a completion.
            _skill("k3", 3, is_required=False),
            _skill("k4", 4, is_active=False),
        ]
    )
    await real_db["test_attempts"].insert_many(
        [
            _attempt("wiped", True),
            _attempt("never", False),
            # A pass in another academy is not a pass for acad-1's student.
            _attempt("other", True, academy="acad-2"),
        ]
    )
    await real_db["student_skill_progress"].insert_many(
        [
            _skill_row("wiped", "k1", "NOT_STARTED"),
            _skill_row("never", "k1", "NOT_STARTED"),
            _skill_row("other", "k1", "NOT_STARTED"),
            _skill_row("done", "k1", "PASSED"),
            _skill_row("done", "k2", "PASSED"),
        ]
    )
    await real_db["student_level_progress"].insert_many(
        [
            _level_row("wiped", "completed"),
            _level_row("done", "completed"),
            _level_row("never", "active"),
        ]
    )
    names = ("skills", "student_skill_progress", "student_level_progress", "test_attempts")
    before = {n: await real_db[n].find({}, {"_id": 0}).to_list(None) for n in names}

    report = await audit(real_db)

    assert report["wiped_passes"] == [
        {
            "academy_id": A,
            "student_id": "wiped",
            "skill_id": "k1",
            "level_id": "L1",
            "passing_attempts": 1,
        }
    ]
    assert report["false_completions"] == [
        {
            "academy_id": A,
            "student_id": "wiped",
            "level_id": "L1",
            "progress_id": "p-wiped",
            "missing_skill_ids": ["k1", "k2"],
        }
    ]
    assert report["affected_students"] == 1
    for name, docs in before.items():
        assert await real_db[name].find({}, {"_id": 0}).to_list(None) == docs
