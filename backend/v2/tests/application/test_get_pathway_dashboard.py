"""GetPathwayDashboard edge rules, on in-memory fakes.

The query shapes are exercised on a real mongod in
``contract/test_pathway_dashboard_real_mongo.py``; this pins the rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_pathway_dashboard import (
    GetPathwayDashboard,
    PathwayDashboardRequest,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardStudentRef,
    StudentLevelProgress,
    StudentSkillProgress,
)

NOW = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)  # a Saturday


def _placed(student_id: str, started_at: datetime) -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id=f"p-{student_id}",
        academy_id="a",
        student_id=student_id,
        program_id="prog",
        level_id="L1",
        started_at=started_at,
        created_at=started_at,
    )


def _passed(student_id: str, skill_id: str) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{student_id}-{skill_id}",
        academy_id="a",
        student_id=student_id,
        skill_id=skill_id,
        level_id="L1",
        program_id="prog",
        status="PASSED",
        last_updated_at=NOW,
        last_updated_by="coach",
    )


def _use_case(*, active, passed, stats, pending=()) -> GetPathwayDashboard:
    level = SimpleNamespace(level_id="L1", name="Grip", sequence=1, requires_admin_approval=False)
    skills = [
        SimpleNamespace(skill_id=s, name=s.upper(), is_required=True) for s in ("s1", "s2", "s3")
    ]
    return GetPathwayDashboard(
        level_progress=SimpleNamespace(list_active_for_students=AsyncMock(return_value=active)),
        skill_progress=SimpleNamespace(
            list_for_students=AsyncMock(return_value=passed),
            passed_stats_for_students=AsyncMock(return_value=stats),
        ),
        recommendations=SimpleNamespace(
            list_active_for_students=AsyncMock(
                return_value=[SimpleNamespace(student_id=s) for s in pending]
            )
        ),
        certificates=SimpleNamespace(list_for_students=AsyncMock(return_value=[])),
        levels=SimpleNamespace(
            list_levels_for_program=AsyncMock(return_value=[level]),
            list_skills_for_level=AsyncMock(return_value=skills),
        ),
    )


def _request(*ids: str) -> PathwayDashboardRequest:
    return PathwayDashboardRequest(
        program_id="prog",
        students=[SkillBoardStudentRef(student_id=i, student_name=i.title()) for i in ids],
        now=NOW,
        timezone="America/Chicago",
    )


@pytest.mark.asyncio
async def test_stuck_counts_from_placement_when_never_won_and_spares_new_students() -> None:
    use_case = _use_case(
        active=[_placed("old", NOW - timedelta(weeks=7)), _placed("new", NOW - timedelta(days=3))],
        passed=[],
        stats=[],
    )

    dash = await use_case.execute(_request("old", "new"))

    assert [s.student_id for s in dash.stuck] == ["old"]
    assert dash.stuck[0].last_win_at is None
    assert dash.stuck[0].skills_passed == 0


@pytest.mark.asyncio
async def test_pending_level_up_is_neither_almost_nor_stuck() -> None:
    long_ago = NOW - timedelta(weeks=9)
    use_case = _use_case(
        active=[_placed("q", long_ago), _placed("a", long_ago)],
        passed=[_passed("q", "s1"), _passed("q", "s2"), _passed("a", "s1"), _passed("a", "s2")],
        stats=[
            {"student_id": "q", "last_passed_at": long_ago, "passed_since": 0},
            {"student_id": "a", "last_passed_at": long_ago, "passed_since": 0},
        ],
        pending=("q",),
    )

    dash = await use_case.execute(_request("q", "a"))

    assert [(a.student_id, a.missing_skill_name) for a in dash.almost_there] == [("a", "S3")]
    # Almost there and stuck are not exclusive: two skills in, then nothing for 9 weeks.
    assert [s.student_id for s in dash.stuck] == ["a"]


@pytest.mark.asyncio
async def test_duplicate_active_rows_count_a_student_once() -> None:
    long_ago = NOW - timedelta(weeks=9)
    use_case = _use_case(
        active=[_placed("d", long_ago), _placed("d", long_ago)], passed=[], stats=[]
    )

    dash = await use_case.execute(_request("d", "u"))

    assert dash.levels[0].player_count == 1
    assert dash.unplaced_count == 1
    assert [s.student_id for s in dash.stuck] == ["d"]
    assert (dash.stuck[0].skills_passed, dash.stuck[0].skills_total) == (0, 3)
