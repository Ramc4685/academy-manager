"""Parent evening win e-mail over a REAL mongod (all migrations applied).

Exercises the real provider (today's PASSED ``student_skill_progress`` rows and
``skill_certificates``), the real claim repo + migration 0213 index, the real
audience resolver and the real preference gate. Only the provider-side mail
transport is the stub, so no e-mail leaves the machine. Skipped when no mongod
is reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.composition.evening_wins import _ParentWinsProvider
from backend.v2.contexts.communications.application.use_cases.send_parent_evening_wins import (
    SendParentEveningWins,
    SendParentEveningWinsCommand,
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
from backend.v2.contexts.communications.infrastructure.mongo_parent_win_send_repo import (
    MongoParentWinSendRepository,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-wins"
OTHER = "acad-other"
CHI = ZoneInfo("America/Chicago")
LOCAL_NOW = datetime(2026, 10, 30, 19, 0, tzinfo=CHI)
TODAY = datetime(2026, 10, 30, 17, 0, tzinfo=CHI).astimezone(UTC)
YESTERDAY = datetime(2026, 10, 29, 20, 0, tzinfo=CHI).astimezone(UTC)


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
        "created_at": YESTERDAY,
        "updated_at": YESTERDAY,
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
                ["Grip", "Ready stance", "Forecourt movement", "Serve", "Clear", "Drop"], 1
            )
        ]
        + [{**common, "skill_id": "L1-1", "level_id": "L1", "sequence": 1, "name": "Footwork"}]
    )

    def row(student: str, skill: str, level: str, status: str, at: datetime) -> dict[str, Any]:
        return {
            "academy_id": ACADEMY,
            "skill_progress_id": f"{student}-{skill}",
            "student_id": student,
            "skill_id": skill,
            "level_id": level,
            "program_id": "prog",
            "status": status,
            "last_updated_at": at,
            "last_updated_by": "coach",
        }

    await db["student_skill_progress"].insert_many(
        [
            row("s-aarav", "L2-1", "L2", "PASSED", YESTERDAY),
            row("s-aarav", "L2-2", "L2", "PASSED", YESTERDAY),
            row("s-aarav", "L2-3", "L2", "PASSED", TODAY),  # the win
            row("s-aarav", "L2-4", "L2", "PRACTICING", TODAY),  # an undone tap
            row("s-diya", "L1-1", "L1", "PASSED", TODAY),  # last skill of L1
            row("s-kim", "L2-1", "L2", "PASSED", YESTERDAY),  # no win today
            row("s-lee", "L2-1", "L2", "PASSED", TODAY),  # unsubscribed parent
            {**row("s-x", "L2-1", "L2", "PASSED", TODAY), "academy_id": OTHER},
        ]
    )
    await db["skill_certificates"].insert_one(
        {
            "academy_id": ACADEMY,
            "cert_id": "c1",
            "student_id": "s-diya",
            "program_id": "prog",
            "level_id": "L1",
            "cert_number": "BLNO-0001",
            "student_name": "Diya Raj",
            "level_name": "Level 1",
            "program_name": "Badminton Pathway",
            "completed_at": TODAY,
            "issued_by": "system",
            "issued_at": TODAY,
        }
    )


def _use_case(db: Any, sent: StubEmailSendPort) -> SendParentEveningWins:
    return SendParentEveningWins(
        claims=MongoParentWinSendRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=GatedEmailSendPort(inner=sent, preferences=MongoEmailPreferenceGate(db)),
        provider=_ParentWinsProvider(
            skill_progress=MongoStudentSkillProgressRepository(db),
            certificates=MongoSkillCertificateRepository(db),
            students=MongoStudentRepository(db),
            skills=MongoSkillRepository(db),
            levels=MongoLevelRepository(db),
            academies=MongoAcademyRepository(db),
        ),
    )


async def test_one_email_per_family_with_a_win_and_none_on_rerun(real_db: Any) -> None:
    await _seed(real_db)
    stub = StubEmailSendPort()
    command = SendParentEveningWinsCommand(academy_id=ACADEMY, local_now=LOCAL_NOW)
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

    # Raj (two children) and Lee (unsubscribed) had wins; Kim did not.
    assert (first.families, first.sent, first.failed) == (2, 1, 1)
    assert (second.sent, second.already_claimed) == (0, 2)
    assert [m["email"] for m in stub.sent] == ["raj@example.test"]
    mail = stub.sent[0]
    assert mail["subject"] == "Today's wins for Aarav and Diya"
    assert str(mail["category"]) == "digest"
    body = mail["body"]
    assert (
        "Aarav mastered Forecourt movement today. That&#x27;s 3 of 6 skills in Level 2, "
        "three to go." in body
    )
    assert "Diya finished Level 1!" in body
    assert "See the certificate" in body
    assert "/parent/progress?child=s-diya" in body
    assert "Footwork" not in body  # celebrated as the level-up, not a skill line
    assert "Ready stance" not in body and "Serve" not in body
    assert "nsubscribe" in body or "email preferences" in body

    rows = await real_db["parent_win_sends"].find({}, {"_id": 0}).to_list(None)
    by_parent = {r["parent_id"]: r for r in rows}
    assert set(by_parent) == {"p-raj", "p-lee"}
    assert by_parent["p-raj"]["status"] == "sent"
    assert by_parent["p-raj"]["digest_date"] == "2026-10-30"
    assert by_parent["p-lee"]["retryable"] is False


async def test_claim_index_from_migration_exists(real_db: Any) -> None:
    names = {idx["name"] async for idx in real_db["parent_win_sends"].list_indexes()}
    assert "parent_win_sends_academy_parent_date_unique" in names


async def test_no_wins_today_sends_nothing(real_db: Any) -> None:
    await _seed(real_db)
    stub = StubEmailSendPort()
    tomorrow = datetime(2026, 10, 31, 19, 0, tzinfo=CHI)
    with tenant_scope(ACADEMY):
        result = await _use_case(real_db, stub).execute(
            SendParentEveningWinsCommand(academy_id=ACADEMY, local_now=tomorrow)
        )
    assert result.families == 0
    assert stub.sent == []
    assert await real_db["parent_win_sends"].count_documents({}) == 0
