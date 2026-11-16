"""Certificate numbering, snapshot, revoke and migration 0234 on a REAL mongod (L5 part B).

Real Mongo because the guarantees live in the database: the counter's
``$inc`` keeps concurrent numbers unique, and 0234's partial unique index is
what allows exactly one issued certificate per level while a revoked one
stays on file.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import timedelta
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.composition.pathway import CertificateNumberAdapter
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.get_certificate_detail import (
    GetCertificateDetail,
    GetCertificateDetailCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.revoke_certificate import (
    RevokeCertificate,
    RevokeCertificateCommand,
)
from backend.v2.contexts.student_progress.domain.errors import CertificateAlreadyRevoked
from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    SkillCertificate,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_audit import (
    MongoCertificateAuditLog,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.tests.contract.test_curriculum_placement_real_mongo import (
    ACADEMY,
    AT,
    _pass,
    _place,
    _seed_curriculum,
    _wire,
)

pytestmark = pytest.mark.asyncio

M0234 = importlib.import_module("backend.v2.migrations.0234_certificate_status_share_indexes")


def _numbers(db: Any) -> CertificateNumberAdapter:
    return CertificateNumberAdapter(
        MongoBillingCounterRepository(db), MongoBillingSettingsRepository(db)
    )


def _cert(cert_id: str, number: str, **extra: Any) -> SkillCertificate:
    return SkillCertificate(
        cert_id=cert_id,
        academy_id=ACADEMY,
        student_id="kid",
        program_id="prog",
        level_id="L1",
        cert_number=number,
        student_name="Kid",
        level_name="One",
        program_name="P",
        completed_at=AT,
        issued_by="owner",
        issued_at=AT,
        **extra,
    )


async def _earn_l1(w: dict[str, Any], rec_id: str = "rec-1") -> str:
    """Place on L1, pass both skills, approve a level-up; the cert id."""
    await w["place"].execute(_place("L1"))
    await _pass(w, "s1")
    await _pass(w, "s2")
    rec = await w["recs"].get_active_for_student("kid", "prog")
    if rec is None:
        await w["recs"].save(
            LevelUpRecommendation(
                rec_id=rec_id,
                academy_id=ACADEMY,
                student_id="kid",
                from_level_id="L1",
                to_level_id="L3",
                program_id="prog",
                recommended_by="coach",
                recommended_at=AT,
            )
        )
    else:
        rec_id = rec.rec_id
    result = await w["review"].execute(
        ReviewLevelUpCommand(rec_id=rec_id, action="approve", reviewed_by="owner")
    )
    assert result.cert_id is not None
    return result.cert_id


async def test_concurrent_mints_never_share_a_number(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        await MongoBillingSettingsRepository(real_db).set_invoice_number_prefix("BLNO")
        numbers = _numbers(real_db)
        minted = await asyncio.gather(*(numbers.next_number() for _ in range(25)))

    assert len(set(minted)) == 25
    assert sorted(minted) == [f"BLNO-C-{n:04d}" for n in range(1, 26)]


async def test_an_academy_without_a_prefix_gets_plain_numbers(real_db: Any) -> None:
    with tenant_scope("acad-no-prefix"):
        first = await _numbers(real_db).next_number()
    with tenant_scope("acad-other"):
        other = await _numbers(real_db).next_number()

    assert (first, other) == ("C-0001", "C-0001")  # each academy counts its own


async def test_renaming_a_skill_after_issue_leaves_the_certificate_alone(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        cert_id = await _earn_l1(w)
        await real_db["skills"].update_one({"skill_id": "s1"}, {"$set": {"name": "Renamed"}})
        detail = await GetCertificateDetail(
            certificates=MongoSkillCertificateRepository(real_db), skill_lookup=w["lookup"]
        ).execute(GetCertificateDetailCommand(student_id="kid", cert_id=cert_id))

    assert detail is not None
    assert detail.skills == ["Grip", "Serve"]
    assert detail.level_number == 1
    assert detail.certificate.cert_number == "T-C-0001"


async def test_revoke_hides_the_certificate_and_a_re_earned_level_issues_a_fresh_one(
    real_db: Any,
) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        repo = MongoSkillCertificateRepository(real_db)
        first = await _earn_l1(w)
        await real_db["skill_certificates"].update_one(
            {"cert_id": first}, {"$set": {"share_token": "tok-1"}}
        )
        revoked = await RevokeCertificate(
            certificates=repo, audit=MongoCertificateAuditLog(real_db)
        ).execute(
            RevokeCertificateCommand(
                student_id="kid", cert_id=first, reason="approved by mistake", revoked_by="owner"
            )
        )
        journey = await repo.list_for_student("kid")
        evening = await repo.list_issued_between(
            AT - timedelta(days=3650), AT + timedelta(days=3650)
        )
        # Back on L1 by hand, earned again: a second, fresh certificate.
        second = await _earn_l1(w, rec_id="rec-2")
        everything = await repo.list_for_student("kid", include_revoked=True)

    assert revoked.status == "revoked" and revoked.revoked_by == "owner"
    assert revoked.share_token is None
    assert journey == [] and evening == []
    assert second != first
    assert sorted(c.status for c in everything) == ["issued", "revoked"]
    raw = await real_db["skill_certificates"].find_one({"cert_id": first})
    assert "share_token" not in raw


async def test_two_issued_certificates_for_one_level_are_refused(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        repo = MongoSkillCertificateRepository(real_db)
        await repo.save(_cert("c1", "N-1"))
        with pytest.raises(DuplicateKeyError):
            await repo.save(_cert("c2", "N-2"))
        await repo.save(_cert("c3", "N-3", status="revoked"))  # a revoked one is fine


async def test_0234_backfills_status_and_aborts_on_duplicate_issued_certificates(
    real_db: Any,
) -> None:
    certs = real_db["skill_certificates"]
    base = _cert("x", "x").model_dump()
    old = {k: v for k, v in base.items() if k not in {"status"}} | {"cert_id": "old"}
    await certs.insert_one(old | {"cert_number": "OLD-1"})
    await M0234.up(real_db)
    assert (await certs.find_one({"cert_id": "old"}))["status"] == "issued"

    # Prod could hold duplicates from before the index; the migration names them.
    await certs.drop_index(M0234.ONE_ISSUED_INDEX)
    await certs.insert_one(old | {"cert_id": "dup", "cert_number": "OLD-2"})
    try:
        with pytest.raises(RuntimeError, match="OLD-1, OLD-2"):
            await M0234.up(real_db)
        assert M0234.ONE_ISSUED_INDEX not in await certs.index_information()
    finally:
        await certs.delete_one({"cert_id": "dup"})
        await M0234.up(real_db)  # later tests in this session lean on the index

    assert M0234.ONE_ISSUED_INDEX in await certs.index_information()


class _AuditFailsOnce(MongoCertificateAuditLog):
    failed = False

    async def record_revoked(self, cert: SkillCertificate) -> bool:
        if not self.failed:
            self.failed = True
            raise RuntimeError("audit write failed")
        return await super().record_revoked(cert)


async def test_a_failed_audit_write_is_recovered_by_the_retry(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        repo = MongoSkillCertificateRepository(real_db)
        await repo.save(_cert("c1", "N-1"))
        revoke = RevokeCertificate(certificates=repo, audit=_AuditFailsOnce(real_db))
        cmd = RevokeCertificateCommand(
            student_id="kid", cert_id="c1", reason="mistake", revoked_by="owner"
        )
        with pytest.raises(RuntimeError):
            await revoke.execute(cmd)
        assert (await revoke.execute(cmd)).status == "revoked"
        with pytest.raises(CertificateAlreadyRevoked):
            await revoke.execute(cmd)

    rows = await real_db["audit_logs"].find({"entity_id": "c1"}).to_list(None)
    assert [(r["action"], r["academy_id"], r["actor_id"], r["reason"]) for r in rows] == [
        ("certificate.revoked", ACADEMY, "owner", "mistake")
    ]
