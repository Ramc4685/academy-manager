"""Owner pathway dashboard on a real ``mongod``: almost there, stuck, KPIs.

Wired as ``composition/pathway.py`` wires it, against the production indexes
and validators (``real_db`` replays every migration), so the
``passed_stats_for_students`` aggregation runs on the real planner. Checks:

* one required skill left -> almost there, naming that skill;
* no pass for 6+ weeks (and on the level that long) -> stuck, with the last win;
* a student placed today with no pass yet is not stuck;
* a student whose level-up is queued is neither;
* another academy's PASSED row for the same student id changes nothing;
* the rule reads ``requires_admin_approval`` across the program's levels.

Synthetic names only. Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.pathway import compose_curriculum, compose_student_progress
from backend.v2.contexts.student_progress.application.use_cases.get_pathway_dashboard import (
    PathwayDashboardRequest,
)
from backend.v2.contexts.student_progress.application.use_cases.mark_skill_mastered import (
    MarkSkillMasteredCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardStudentRef,
    SkillCertificate,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository,
)
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-dash"
OTHER = "acad-other"
ALMOST, STUCK, FRESH, QUEUED, UNPLACED = "stu-almost", "stu-stuck", "stu-fresh", "stu-q", "stu-u"
NAMES = {ALMOST: "Ava", STUCK: "Sid", FRESH: "Fay", QUEUED: "Quinn", UNPLACED: "Uma"}


async def _tap(progress: Any, program_id: str, skill_id: str, student_id: str) -> None:
    await progress.mark_skill_mastered.execute(
        MarkSkillMasteredCommand(
            skill_id=skill_id, program_id=program_id, student_ids=[student_id], coach_id="coach-x"
        )
    )


@pytest.mark.asyncio
async def test_dashboard_almost_stuck_and_kpis(real_db: Any) -> None:
    now = datetime.now(UTC)
    with tenant_scope(ACADEMY):
        for student_id in NAMES:
            await real_db["enrollments"].insert_one(
                {
                    "academy_id": ACADEMY,
                    "enrollment_id": f"enr-{student_id}",
                    "session_id": "sess-dash",
                    "student_id": student_id,
                    "status": "active",
                    "enrolled_at": datetime(2026, 9, 1, tzinfo=UTC),
                }
            )
        curriculum = compose_curriculum(real_db)
        progress = compose_student_progress(real_db)
        program = await curriculum.seed_badminton.execute(created_by="owner")
        program_id = program.program_id
        levels = sorted(
            await curriculum.list_levels.execute(program_id), key=lambda lv: lv.sequence
        )
        level1 = levels[0]
        skills = sorted(
            await real_db["skills"].find({"level_id": level1.level_id}).to_list(None),
            key=lambda s: s["sequence"],
        )
        required = [s for s in skills if s.get("is_required", True)]
        assert len(required) >= 2

        for student_id in (ALMOST, STUCK, FRESH, QUEUED):
            await progress.place_student.execute(
                PlaceStudentInLevelCommand(
                    student_id=student_id,
                    program_id=program_id,
                    level_id=level1.level_id,
                    placed_by="owner",
                )
            )
        for skill in required[:-1]:
            await _tap(progress, program_id, skill["skill_id"], ALMOST)
        for skill in required:
            await _tap(progress, program_id, skill["skill_id"], QUEUED)

        # STUCK: on the level 10 weeks, one win 8 weeks ago.
        await _tap(progress, program_id, required[0]["skill_id"], STUCK)
        eight_weeks_ago = now - timedelta(weeks=8)
        await real_db["student_skill_progress"].update_one(
            {"academy_id": ACADEMY, "student_id": STUCK, "skill_id": required[0]["skill_id"]},
            {"$set": {"last_updated_at": eight_weeks_ago}},
        )
        await real_db["student_level_progress"].update_many(
            {"academy_id": ACADEMY, "student_id": STUCK},
            {"$set": {"started_at": now - timedelta(weeks=10)}},
        )
        # Another academy's recent win for the same student id must not count.
        await real_db["student_skill_progress"].insert_one(
            {
                "academy_id": OTHER,
                "skill_progress_id": "ssp-other",
                "student_id": STUCK,
                "skill_id": required[1]["skill_id"],
                "level_id": level1.level_id,
                "program_id": program_id,
                "status": "PASSED",
                "introduced_at": now,
                "last_updated_at": now,
                "last_updated_by": "coach-y",
            }
        )

        certs = MongoSkillCertificateRepository(real_db)
        for cert_id, issued_at in (("c-now", now), ("c-old", now - timedelta(days=400))):
            await certs.save(
                SkillCertificate(
                    cert_id=cert_id,
                    academy_id=ACADEMY,
                    student_id=STUCK,
                    program_id=program_id,
                    level_id=level1.level_id,
                    cert_number=cert_id,
                    student_name="Sid",
                    level_name=level1.name,
                    program_name=program.name,
                    completed_at=issued_at,
                    issued_by="owner",
                    issued_at=issued_at,
                )
            )

        request = PathwayDashboardRequest(
            program_id=program_id,
            students=[SkillBoardStudentRef(student_id=k, student_name=v) for k, v in NAMES.items()],
            now=now,
            timezone="America/Chicago",
        )
        dash = await progress.get_pathway_dashboard.execute(request)

        assert [a.student_id for a in dash.almost_there] == [ALMOST]
        assert dash.almost_there[0].missing_skill_name == required[-1]["name"]
        assert [s.student_id for s in dash.stuck] == [STUCK]
        stuck = dash.stuck[0]
        assert stuck.skills_passed == 1
        assert stuck.skills_total == len(required)
        assert abs((stuck.last_win_at - eight_weeks_ago).total_seconds()) < 1  # type: ignore[operator]
        # ALMOST's and QUEUED's taps are this week; STUCK's backdated one is not.
        assert dash.skills_mastered_this_week == (len(required) - 1) + len(required)
        assert dash.level_ups_this_month == 1
        assert dash.unplaced_count == 1
        assert dash.levels[0].player_count == 4
        assert sum(lv.player_count for lv in dash.levels) == 4
        assert dash.level_up_rule == "automatic"

        await real_db["skill_levels"].update_one(
            {"level_id": level1.level_id}, {"$set": {"requires_admin_approval": True}}
        )
        assert (await progress.get_pathway_dashboard.execute(request)).level_up_rule == "mixed"
