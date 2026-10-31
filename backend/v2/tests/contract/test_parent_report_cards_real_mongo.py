"""Parent monthly report card over a REAL mongod (all migrations applied).

Exercises the real provider (the month's PASSED ``student_skill_progress``
rows, ``attendance`` marks, ``student_level_progress``, ``skills`` and
``curriculum_video_refs``), the real claim repo + migration 0214 index, the
real audience resolver and the real preference gate. Only the provider-side
mail transport is the stub, so no e-mail leaves the machine. Skipped when no
mongod is reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.composition.report_cards import _ReportCardProvider
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.communications.application.unsubscribe_footer import (
    render_unsubscribe_footer,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_report_cards import (
    SendParentReportCards,
    SendParentReportCardsCommand,
)
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.communications.infrastructure.mongo_email_preference_repo import (
    MongoEmailPreferenceGate,
    MongoEmailPreferenceRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_parent_report_card_send_repo import (
    MongoParentReportCardSendRepository,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-cards"
OTHER = "acad-other"
CHI = ZoneInfo("America/Chicago")
LOCAL_NOW = datetime(2026, 11, 1, 9, 0, tzinfo=CHI)
OCT = datetime(2026, 10, 14, 17, 0, tzinfo=CHI).astimezone(UTC)
SEPT = datetime(2026, 9, 30, 17, 0, tzinfo=CHI).astimezone(UTC)
# Local Oct 31 evening is already Nov 1 in UTC: still October for the card.
OCT_31_LATE = datetime(2026, 10, 31, 21, 0, tzinfo=CHI).astimezone(UTC)
NOV = datetime(2026, 11, 1, 8, 0, tzinfo=CHI).astimezone(UTC)


async def _seed(db: Any) -> None:
    await db["academies"].insert_one(
        {"academy_id": ACADEMY, "slug": "blno", "display_name": "BLNO"}
    )
    await db["users"].insert_many(
        [
            {"academy_id": ACADEMY, "user_id": "p-raj", "email": "raj@example.test"},
            {"academy_id": ACADEMY, "user_id": "p-kim", "email": "kim@example.test"},
            {"academy_id": ACADEMY, "user_id": "p-lee", "email": "lee@example.test"},
        ]
    )
    await db["students"].insert_many(
        [
            {"academy_id": ACADEMY, "student_id": s, "parent_id": p, "full_name": n}
            for s, p, n in [
                ("s-aarav", "p-raj", "Aarav Raj"),
                ("s-diya", "p-raj", "Diya Raj"),
                ("s-kim", "p-kim", "Mina Kim"),
                ("s-lee", "p-lee", "Jo Lee"),
            ]
        ]
    )
    common = {
        "academy_id": ACADEMY,
        "program_id": "prog",
        "is_active": True,
        "created_at": SEPT,
        "updated_at": SEPT,
        "created_by": "owner",
    }
    await db["skill_levels"].insert_many(
        [
            {**common, "level_id": "L1", "sequence": 1, "name": "Level 1"},
            {**common, "level_id": "L2", "sequence": 2, "name": "Level 2"},
        ]
    )
    await db["skills"].insert_many(
        [
            {**common, "skill_id": f"L2-{i}", "level_id": "L2", "sequence": i, "name": n}
            for i, n in enumerate(
                ["Grip", "Ready stance", "Forecourt movement", "Backhand net shot"], 1
            )
        ]
        + [{**common, "skill_id": "L1-1", "level_id": "L1", "sequence": 1, "name": "Footwork"}]
    )
    await db["curriculum_video_refs"].insert_one(
        {
            "academy_id": ACADEMY,
            "ref_id": "v1",
            "program_id": "prog",
            "scope": "SKILL",
            "level_id": "L2",
            "skill_id": "L2-4",
            "title": "Backhand net shot drill",
            "url": "https://video.test/backhand",
            "display_order": 0,
            "content_hash": "h",
            "is_active": True,
            "created_at": SEPT,
            "created_by": "owner",
        }
    )
    await db["student_level_progress"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "progress_id": f"lp-{s}-{lvl}",
                "student_id": s,
                "program_id": "prog",
                "level_id": lvl,
                "status": status,
                "started_at": SEPT,
                "completed_at": None,
                "created_at": SEPT,
            }
            for s, lvl, status in [
                ("s-aarav", "L1", "completed"),
                ("s-aarav", "L2", "active"),
                ("s-diya", "L1", "active"),
                ("s-lee", "L2", "active"),
            ]
        ]
    )

    def skill(student: str, skill_id: str, level: str, status: str, at: datetime) -> dict[str, Any]:
        return {
            "academy_id": ACADEMY,
            "skill_progress_id": f"{student}-{skill_id}",
            "student_id": student,
            "skill_id": skill_id,
            "level_id": level,
            "program_id": "prog",
            "status": status,
            "last_updated_at": at,
            "last_updated_by": "coach",
        }

    await db["student_skill_progress"].insert_many(
        [
            skill("s-aarav", "L2-1", "L2", "PASSED", SEPT),  # last month
            skill("s-aarav", "L2-2", "L2", "PASSED", OCT),
            skill("s-aarav", "L2-3", "L2", "PASSED", OCT_31_LATE),
            skill("s-diya", "L1-1", "L1", "PRACTICING", OCT),
            skill("s-kim", "L2-1", "L2", "PASSED", NOV),  # next month
            skill("s-lee", "L2-1", "L2", "PASSED", OCT),
            {**skill("s-x", "L2-1", "L2", "PASSED", OCT), "academy_id": OTHER},
        ]
    )

    def mark(student: str, n: int, status: str, at: datetime) -> dict[str, Any]:
        return {
            "academy_id": ACADEMY,
            "attendance_id": f"a-{student}-{n}",
            "occurrence_id": f"occ-{n}",
            "session_id": "sess",
            "student_id": student,
            "marked_by": "coach",
            "marked_at": at,
            "status": status,
            "client_app_version": "test",
            "entry_source": "enrollment",
        }

    await db["attendance"].insert_many(
        [mark("s-aarav", n, "present", OCT) for n in range(1, 7)]
        + [
            mark("s-aarav", 7, "late", OCT),
            mark("s-aarav", 8, "absent", OCT),
            mark("s-aarav", 9, "voided", OCT),  # annulled: not counted
            mark("s-aarav", 10, "present", SEPT),  # last month
            mark("s-diya", 1, "present", OCT),
            mark("s-diya", 2, "absent", OCT),
            mark("s-kim", 1, "present", NOV),  # next month
        ]
    )


def _use_case(db: Any, sent: StubEmailSendPort) -> SendParentReportCards:
    return SendParentReportCards(
        claims=MongoParentReportCardSendRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=GatedEmailSendPort(inner=sent, preferences=MongoEmailPreferenceGate(db)),
        provider=_ReportCardProvider(
            skill_progress=MongoStudentSkillProgressRepository(db),
            level_progress=MongoStudentLevelProgressRepository(db),
            attendance=MongoAttendanceRepository(db),
            students=MongoStudentRepository(db),
            skills=MongoSkillRepository(db),
            levels=MongoLevelRepository(db),
            video_refs=MongoCurriculumVideoRefRepository(db),
            academies=MongoAcademyRepository(db),
        ),
    )


async def test_one_card_per_family_for_last_month_and_none_on_rerun(real_db: Any) -> None:
    await _seed(real_db)
    stub = StubEmailSendPort()
    command = SendParentReportCardsCommand(academy_id=ACADEMY, local_now=LOCAL_NOW)
    with tenant_scope(ACADEMY):
        await MongoEmailPreferenceRepository(real_db).set_opt_outs(
            user_id="p-lee",
            email="lee@example.test",
            campaigns_opted_out=False,
            digests_opted_out=True,
            source="test",
        )
        first = await _use_case(real_db, stub).execute(command)
        second = await _use_case(real_db, stub).execute(command)

    # Raj (two children) and Lee (unsubscribed) had an October; Kim did not.
    assert (first.families, first.sent, first.failed) == (2, 1, 1)
    assert (second.sent, second.already_claimed) == (0, 2)
    assert [m["email"] for m in stub.sent] == ["raj@example.test"]
    mail = stub.sent[0]
    assert mail["subject"] == "October for Aarav and Diya"
    assert str(mail["category"]) == "digest"
    body = mail["body"]
    aarav, diya = body.split("October for Diya")
    # Aarav: 2 new skills (Sept's not counted), 7 of 8 marks (voided dropped).
    assert ">2</div>" in aarav and ">7/8</div>" in aarav
    assert ">L2</div>" in aarav and "Level 2" in aarav
    assert "Focus for November: Backhand net shot." in aarav
    assert 'href="https://video.test/backhand"' in aarav
    # Diya: nothing passed, 1 of 2 classes, focus on Level 1 with no video.
    assert ">0</div>" in diya and ">1/2</div>" in diya and ">L1</div>" in diya
    assert "Focus for November: Footwork." in diya and "practice video" not in diya
    assert "/parent/progress?child=s-diya" in diya
    assert render_unsubscribe_footer(None) in body

    rows = await real_db["parent_report_card_sends"].find({}, {"_id": 0}).to_list(None)
    by_parent = {r["parent_id"]: r for r in rows}
    assert set(by_parent) == {"p-raj", "p-lee"}
    assert by_parent["p-raj"]["status"] == "sent"
    assert by_parent["p-raj"]["digest_date"] == "2026-10"
    assert by_parent["p-lee"]["retryable"] is False


async def test_claim_index_from_migration_exists(real_db: Any) -> None:
    names = {idx["name"] async for idx in real_db["parent_report_card_sends"].list_indexes()}
    assert "parent_report_card_sends_academy_parent_month_unique" in names


async def test_not_the_first_sends_nothing(real_db: Any) -> None:
    await _seed(real_db)
    stub = StubEmailSendPort()
    with tenant_scope(ACADEMY):
        result = await _use_case(real_db, stub).execute(
            SendParentReportCardsCommand(
                academy_id=ACADEMY, local_now=datetime(2026, 11, 2, 9, 0, tzinfo=CHI)
            )
        )
    assert result.families == 0
    assert stub.sent == []
    assert await real_db["parent_report_card_sends"].count_documents({}) == 0
