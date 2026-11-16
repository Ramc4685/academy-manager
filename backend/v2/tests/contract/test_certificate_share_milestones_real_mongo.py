"""Certificate share links and milestone records on a REAL mongod (L5B PR2).

Real Mongo because the guarantees live in the database: the share token is
found through the per-academy index (0234), so a token resolves only inside
the academy the request host names, and 0241's partial unique index is what
keeps one milestone record per student per milestone under concurrent writes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from backend.v2.contexts.student_progress.application.use_cases.certificate_share import (
    GetSharedCertificate,
    SetCertificateShare,
    SetCertificateShareCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.progress_milestones import (
    RecordReachedMilestones,
    UpdateProgressSettings,
    UpdateProgressSettingsCommand,
)
from backend.v2.contexts.student_progress.domain.errors import CertificateNotFound
from backend.v2.contexts.student_progress.domain.models import (
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_audit import (
    MongoCertificateAuditLog,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_milestone_repo import (
    MongoStudentMilestoneRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_progress_settings_repo import (
    MongoProgressSettingsRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.tests.fixtures.public_page import ACADEMY, OTHER, RIVERSIDE_HOST, build_app

pytestmark = pytest.mark.asyncio

LAKESIDE_HOST = "lakeside-academy.courtmastr.test"
ISSUED = datetime(2026, 11, 2, 23, 30, tzinfo=UTC)  # 18:30 in New York on Nov 2
TOKEN = "tok_" + "A" * 18


async def _seed_academies(db: Any) -> None:
    await db["academies"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "slug": "riverside-academy",
                "display_name": "Riverside Shuttle Club",
                "timezone": "America/New_York",
                "currency": "USD",
                "logo_url": "https://cdn.example.test/riverside.png",
                "contact_email": "owner.private@example.test",
            },
            {"academy_id": OTHER, "slug": "lakeside-academy", "display_name": "Lakeside"},
        ]
    )


def _cert(
    cert_id: str = "cert-1", student_id: str = "stu-secret-1", **extra: Any
) -> SkillCertificate:
    return SkillCertificate(
        cert_id=cert_id,
        academy_id=ACADEMY,
        student_id=student_id,
        program_id="prog-secret",
        level_id="level-secret",
        cert_number="RIV-C-0007",
        student_name="Maya Secretsurname",
        level_name="Shuttle Starter",
        program_name="Juniors",
        completed_at=ISSUED,
        issued_by="coach-secret",
        issued_at=ISSUED,
        skill_names=["Grip", "Serve"],
        level_number=2,
        level_color="#2563EB",
        **extra,
    )


def _share(db: Any) -> SetCertificateShare:
    return SetCertificateShare(
        certificates=MongoSkillCertificateRepository(db), audit=MongoCertificateAuditLog(db)
    )


def _cmd(shared: bool, student_id: str = "stu-secret-1") -> SetCertificateShareCommand:
    return SetCertificateShareCommand(
        student_id=student_id, cert_id="cert-1", actor_id="parent-1", shared=shared
    )


async def _share_audit_rows(db: Any) -> list[dict[str, Any]]:
    cursor = db["audit_logs"].find({"entity_type": "certificate"}, sort=[("created_at", 1)])
    return [row async for row in cursor]


# --- share links -------------------------------------------------------------------


async def test_share_is_idempotent_and_audited_once_per_change(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        await MongoSkillCertificateRepository(real_db).save(_cert())
        first = await _share(real_db).execute(_cmd(True))
        again = await _share(real_db).execute(_cmd(True))
        assert first.share_token and again.share_token == first.share_token
        off = await _share(real_db).execute(_cmd(False))
        off_again = await _share(real_db).execute(_cmd(False))
        assert off.share_token is None and off_again.share_token is None
        fresh = await _share(real_db).execute(_cmd(True))
    assert fresh.share_token and fresh.share_token != first.share_token
    rows = await _share_audit_rows(real_db)
    assert [r["action"] for r in rows] == [
        "certificate.share_created",
        "certificate.share_revoked",
        "certificate.share_created",
    ]
    assert all(r["actor_id"] == "parent-1" and r["academy_id"] == ACADEMY for r in rows)
    # The token is a capability: the audit trail never carries it.
    assert first.share_token not in str(rows) and fresh.share_token not in str(rows)


async def test_share_refuses_a_revoked_or_other_childs_certificate(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        repo = MongoSkillCertificateRepository(real_db)
        await repo.save(_cert())
        with pytest.raises(CertificateNotFound):
            await _share(real_db).execute(_cmd(True, student_id="someone-else"))
        await repo.revoke("stu-secret-1", "cert-1", at=ISSUED, by="owner", reason="error")
        with pytest.raises(CertificateNotFound):
            await _share(real_db).execute(_cmd(True))
    assert await _share_audit_rows(real_db) == []


async def test_token_resolves_only_in_its_own_academy_and_only_while_issued(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        repo = MongoSkillCertificateRepository(real_db)
        await repo.save(_cert())
        assert await repo.set_share_token("stu-secret-1", "cert-1", TOKEN)
        found = await repo.get_issued_by_share_token(TOKEN)
    assert found is not None and found.cert_id == "cert-1"
    with tenant_scope(OTHER):
        assert (
            await MongoSkillCertificateRepository(real_db).get_issued_by_share_token(TOKEN) is None
        )
    with tenant_scope(ACADEMY):
        await repo.revoke("stu-secret-1", "cert-1", at=ISSUED, by="owner", reason="error")
        assert await repo.get_issued_by_share_token(TOKEN) is None


async def test_account_deletion_still_scrubs_a_parent_minted_link(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        repo = MongoSkillCertificateRepository(real_db)
        await repo.save(_cert())
        shared = await _share(real_db).execute(_cmd(True))
        assert shared.share_token
        await repo.anonymise_student("stu-secret-1", student_name="Deleted student")
        assert await repo.get_issued_by_share_token(shared.share_token) is None
    doc = await real_db["skill_certificates"].find_one({"cert_id": "cert-1"})
    assert "share_token" not in doc


async def test_public_share_name_follows_the_academy_rule(real_db: Any) -> None:
    await _seed_academies(real_db)
    with tenant_scope(ACADEMY):
        repo = MongoSkillCertificateRepository(real_db)
        await repo.save(_cert())
        await repo.set_share_token("stu-secret-1", "cert-1", TOKEN)
        read = GetSharedCertificate(
            certificates=repo, settings=MongoProgressSettingsRepository(real_db)
        )
        assert (await read.execute(TOKEN)).recipient_name == "Maya"  # type: ignore[union-attr]
        await _update(real_db, enabled=False, milestones=[], share_name="initial")
        assert (await read.execute(TOKEN)).recipient_name == "M."  # type: ignore[union-attr]


# --- the public route ----------------------------------------------------------------


async def test_public_route_tenant_from_host_minimum_fields_and_one_404(real_db: Any) -> None:
    await _seed_academies(real_db)
    with tenant_scope(ACADEMY):
        repo = MongoSkillCertificateRepository(real_db)
        await repo.save(_cert())
        await repo.set_share_token("stu-secret-1", "cert-1", TOKEN)
    # In-loop ASGI client: the motor client belongs to this test's event loop.
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(real_db)), base_url="http://test"
    )
    url = f"/api/v2/public/certificates/{TOKEN}"

    ok = await client.get(url, headers={"host": RIVERSIDE_HOST})
    assert ok.status_code == 200, ok.text
    assert ok.headers["cache-control"] == "no-store"
    assert ok.json() == {
        "academy": {
            "name": "Riverside Shuttle Club",
            "logo_url": "https://cdn.example.test/riverside.png",
            "brand_color": None,
            "brand_fill": ok.json()["academy"]["brand_fill"],
            "brand_on_color": ok.json()["academy"]["brand_on_color"],
        },
        "recipient_name": "Maya",
        "level_name": "Shuttle Starter",
        "level_number": 2,
        "level_color": "#2563EB",
        "cert_number": "RIV-C-0007",
        "issued_on": "2026-11-02",  # academy-local date, not the UTC one
    }
    for private in (
        "Secretsurname",
        "stu-secret-1",
        "prog-secret",
        "level-secret",
        "coach-secret",
        "owner.private@example.test",
        "Grip",
        "Juniors",
        "cert-1",
    ):
        assert private not in ok.text, private

    with tenant_scope(ACADEMY):
        await real_db["skill_certificates"].insert_one(
            _cert("cert-2", "stu-2").model_dump()
            | {"cert_number": "RIV-C-0008", "share_token": "tok_revoked_000000000"}
        )
        await repo.revoke("stu-2", "cert-2", at=ISSUED, by="owner", reason="x")
    misses = [
        (RIVERSIDE_HOST, "tok_unknown_0000000000"),
        (RIVERSIDE_HOST, "tok_revoked_000000000"),
        (RIVERSIDE_HOST, "short"),
        (LAKESIDE_HOST, TOKEN),  # right token, another academy's host
        ("nobody.example.test", TOKEN),  # no academy for this host
    ]
    bodies = set()
    for host, token in misses:
        miss = await client.get(f"/api/v2/public/certificates/{token}", headers={"host": host})
        assert miss.status_code == 404, (host, token, miss.text)
        bodies.add(miss.text)
    assert len(bodies) == 1


# --- milestones ----------------------------------------------------------------------


async def _update(
    db: Any, *, enabled: bool, milestones: list[tuple[str, int]], share_name: str = "first_name"
) -> Any:
    return await UpdateProgressSettings(
        settings=MongoProgressSettingsRepository(db), audit=MongoCertificateAuditLog(db)
    ).execute(
        UpdateProgressSettingsCommand(
            actor_id="owner-1",
            milestones_enabled=enabled,
            milestones=milestones,
            share_name=share_name,
        )
    )


def _recorder(db: Any) -> RecordReachedMilestones:
    return RecordReachedMilestones(
        settings=MongoProgressSettingsRepository(db),
        skill_progress=MongoStudentSkillProgressRepository(db),
        level_progress=MongoStudentLevelProgressRepository(db),
        milestones=MongoStudentMilestoneRepository(db),
    )


async def _pass_skills(db: Any, student_id: str, times: list[datetime]) -> None:
    repo = MongoStudentSkillProgressRepository(db)
    for n, at in enumerate(times):
        await repo.save(
            StudentSkillProgress(
                skill_progress_id=f"sp-{student_id}-{n}",
                academy_id=ACADEMY,
                student_id=student_id,
                skill_id=f"skill-{n}",
                level_id="L1",
                program_id="prog",
                status="PASSED",
                last_updated_at=at,
                last_updated_by="coach",
            )
        )


async def test_milestones_are_off_by_default_and_record_nothing(real_db: Any) -> None:
    await _seed_academies(real_db)
    now = datetime.now(UTC)
    with tenant_scope(ACADEMY):
        await _pass_skills(real_db, "kid", [now] * 5)
        assert await _recorder(real_db).execute("kid") == []
    assert await real_db["student_milestones"].count_documents({}) == 0


async def test_settings_change_is_targeted_audited_and_keeps_since(real_db: Any) -> None:
    await _seed_academies(real_db)
    with tenant_scope(ACADEMY):
        first = await _update(real_db, enabled=True, milestones=[("skills_passed", 3)])
        unchanged = await _update(real_db, enabled=True, milestones=[("skills_passed", 3)])
        second = await _update(
            real_db, enabled=True, milestones=[("skills_passed", 3), ("levels_completed", 1)]
        )
    assert [m.key for m in unchanged.milestones] == ["skills_passed:3"]
    since = {m.key: m.since for m in second.milestones}
    # Kept, not reset (Mongo stores milliseconds).
    assert abs(since["skills_passed:3"] - first.milestones[0].since) < timedelta(milliseconds=1)
    assert since["levels_completed:1"] > since["skills_passed:3"]
    audits = await real_db["audit_logs"].count_documents({"action": "progress_settings.changed"})
    assert audits == 2  # the no-op save wrote nothing
    academy = await real_db["academies"].find_one({"academy_id": ACADEMY})
    # The targeted write left the rest of the record alone.
    assert academy["display_name"] == "Riverside Shuttle Club"
    assert academy["contact_email"] == "owner.private@example.test"


async def test_milestone_is_deterministic_idempotent_and_going_forward_only(real_db: Any) -> None:
    await _seed_academies(real_db)
    with tenant_scope(ACADEMY):
        settings = await _update(real_db, enabled=True, milestones=[("skills_passed", 3)])
        since = settings.milestones[0].since
        before = since - timedelta(days=2)
        after = since + timedelta(hours=1)
        # "old" reached 3 before the threshold existed: no celebration, ever.
        await _pass_skills(real_db, "old", [before, before, before, after])
        # "new" reaches 3 after: one record, reached when the 3rd skill passed.
        await _pass_skills(real_db, "new", [before, after, after + timedelta(minutes=5)])
        recorder = _recorder(real_db)
        assert await recorder.execute("old") == []
        results = await asyncio.gather(*(recorder.execute("new") for _ in range(8)))
        await recorder.execute("new")
    assert all(len(r) == 1 for r in results)
    rows = [row async for row in real_db["student_milestones"].find({})]
    assert len(rows) == 1
    assert rows[0]["student_id"] == "new" and rows[0]["milestone_key"] == "skills_passed:3"
    third_pass = after + timedelta(minutes=5)  # Mongo keeps milliseconds
    assert abs(rows[0]["reached_at"].replace(tzinfo=UTC) - third_pass) < timedelta(milliseconds=1)


async def test_levels_completed_milestone_counts_completed_levels(real_db: Any) -> None:
    await _seed_academies(real_db)
    with tenant_scope(ACADEMY):
        await _update(real_db, enabled=True, milestones=[("levels_completed", 2)])
        levels = MongoStudentLevelProgressRepository(real_db)
        done = datetime.now(UTC) + timedelta(minutes=1)
        for n, status in enumerate(["completed", "completed", "active"]):
            await levels.save(
                StudentLevelProgress(
                    progress_id=f"lp-{n}",
                    academy_id=ACADEMY,
                    student_id="kid",
                    program_id="prog",
                    level_id=f"L{n}",
                    status=status,  # type: ignore[arg-type]
                    started_at=done,
                    completed_at=done + timedelta(minutes=n) if status == "completed" else None,
                    created_at=done,
                )
            )
        reached = await _recorder(real_db).execute("kid")
        # Off again: the journey and email stay silent, the record stays on file.
        await _update(real_db, enabled=False, milestones=[("levels_completed", 2)])
        assert await _recorder(real_db).execute("kid") == []
    assert [(m.kind, m.count) for m in reached] == [("levels_completed", 2)]
