"""The placement audit row is written by the use case, after the placement, once.

It used to be written by the route with a random id: a retry doubled it, and
the route (not the use case) owned the trail. Now ``PlaceStudentInLevel`` writes
it last through ``PlacementAuditLog`` with a deterministic id, like the
certificate revoke row.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevel,
)
from backend.v2.contexts.student_progress.domain.errors import LevelNotConfigured
from backend.v2.contexts.student_progress.infrastructure.mongo_placement_audit import (
    MongoPlacementAuditLog,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.contract.test_curriculum_placement_real_mongo import (
    ACADEMY,
    _Live,
    _place,
    _seed_curriculum,
    _wire,
)

pytestmark = pytest.mark.asyncio


def _placer(db: Any, audit: Any) -> PlaceStudentInLevel:
    w = _wire(db)
    return PlaceStudentInLevel(
        level_progress=w["level_progress"],
        skill_progress=w["skill_progress"],
        skill_lookup=w["lookup"],
        recommendations=w["recs"],
        enrollment_lookup=_Live(),
        audit=audit,
    )


async def _rows(db: Any) -> list[dict[str, Any]]:
    return await db["audit_logs"].find({"action": "student.pathway_placed"}).to_list(None)


async def test_one_row_per_placement_and_none_for_a_refused_one(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        placer = _placer(real_db, MongoPlacementAuditLog(real_db))
        progress = await placer.execute(_place("L1"))
        await placer.execute(_place("L1"))  # a retry of the same placement
        with pytest.raises(LevelNotConfigured):
            await placer.execute(_place("no-such-level"))

    (row,) = await _rows(real_db)
    assert row["audit_id"].startswith(f"student.pathway_placed:{progress.progress_id}:")
    assert row["academy_id"] == ACADEMY
    assert row["actor_id"] == "owner"
    assert row["after"]["level_id"] == "L1"


async def test_a_re_placement_by_another_admin_keeps_its_own_row(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        placer = _placer(real_db, MongoPlacementAuditLog(real_db))
        await placer.execute(_place("L1"))
        await placer.execute(_place("L1").model_copy(update={"placed_by": "admin-2"}))
        await placer.execute(_place("L1").model_copy(update={"placed_by": "admin-2"}))  # replay

    rows = await _rows(real_db)
    assert sorted(r["actor_id"] for r in rows) == ["admin-2", "owner"]


async def test_a_failed_audit_write_is_repaired_by_the_retry(real_db: Any) -> None:
    await _seed_curriculum(real_db)

    class _FailsOnce(MongoPlacementAuditLog):
        failed = False

        async def record_placed(self, **kwargs: Any) -> bool:
            if not self.failed:
                self.failed = True
                raise RuntimeError("audit write lost")
            return await super().record_placed(**kwargs)

    with tenant_scope(ACADEMY):
        placer = _placer(real_db, _FailsOnce(real_db))
        with pytest.raises(RuntimeError):
            await placer.execute(_place("L1"))
        assert await _rows(real_db) == []  # never a row before the placement is done
        progress = await placer.execute(_place("L1"))

    (row,) = await _rows(real_db)
    assert row["after"]["progress_id"] == progress.progress_id


M0240 = importlib.import_module("backend.v2.migrations.0240_audit_logs_audit_id_unique")


async def test_0240_names_duplicates_then_makes_audit_id_unique_per_academy(real_db: Any) -> None:
    audit = real_db["audit_logs"]
    assert M0240.INDEX_NAME in await audit.index_information()

    await audit.drop_index(M0240.INDEX_NAME)
    row = {"academy_id": ACADEMY, "audit_id": "student.pathway_placed:p1"}
    await audit.insert_many([dict(row), dict(row), {"academy_id": ACADEMY, "audit_id": ""}])
    try:
        with pytest.raises(RuntimeError, match=f"{ACADEMY}/student.pathway_placed:p1 x2"):
            await M0240.up(real_db)
        assert M0240.INDEX_NAME not in await audit.index_information()
    finally:
        await audit.delete_one(row)
        await M0240.up(real_db)  # later tests in this session lean on the index

    with pytest.raises(DuplicateKeyError):
        await audit.insert_one(dict(row))
    # Rows without an audit_id, and other academies, are outside the index.
    await audit.insert_one({"academy_id": ACADEMY, "audit_id": ""})
    await audit.insert_one({"academy_id": "other", "audit_id": row["audit_id"]})
