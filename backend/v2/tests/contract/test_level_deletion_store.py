"""Deleting a curriculum level: allowed when unused, refused (409) when anything uses it.

The store, use case and route run against ``db`` (a real mongod in CI), so the
aggregation counts, the cascading delete and tenant scoping are the real ones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.v2.contexts.curriculum.application.errors import LevelInUse
from backend.v2.contexts.curriculum.application.use_cases.manage_levels import (
    DeleteLevel,
    DeleteLevelCommand,
    GetLevelUsage,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_deletion_store import (
    MongoLevelDeletionStore,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.pathway_routes import router as pathway_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http.errors import register_exception_handlers
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 8, 16, 0, tzinfo=UTC)
ACADEMY = "acad-del-a"


async def _seed_level(db, level_id: str, *, academy: str = ACADEMY, skills: int = 2) -> None:
    await db["skill_levels"].insert_one(
        {
            "academy_id": academy,
            "level_id": level_id,
            "program_id": "prog-1",
            "sequence": int(level_id.removeprefix("lv-")),
            "name": f"Level {level_id}",
            "description": "",
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
            "created_by": "ai",
        }
    )
    for i in range(skills):
        skill_id = f"{level_id}-s{i}"
        await db["skills"].insert_one(
            {
                "academy_id": academy,
                "skill_id": skill_id,
                "level_id": level_id,
                "program_id": "prog-1",
                "sequence": i + 1,
                "name": f"Skill {i}",
            }
        )
        for c in range(3):
            await db["skill_criteria"].insert_one(
                {
                    "academy_id": academy,
                    "criterion_id": f"{skill_id}-c{c}",
                    "skill_id": skill_id,
                    "level_id": level_id,
                    "program_id": "prog-1",
                    "description": "x",
                }
            )


def _use_cases(db) -> SimpleNamespace:
    levels = MongoLevelRepository(db)
    store = MongoLevelDeletionStore(db)
    return SimpleNamespace(
        delete_level=DeleteLevel(levels=levels, store=store),
        get_level_usage=GetLevelUsage(levels=levels, store=store),
    )


@pytest.mark.asyncio
async def test_unused_level_is_deleted_with_its_skills_criteria_and_an_audit_row(db) -> None:
    await _seed_level(db, "lv-7")
    await _seed_level(db, "lv-6")  # a sibling that must survive
    await _seed_level(db, "lv-7", academy="acad-del-b")  # same id, other academy

    with tenant_scope(ACADEMY):
        deleted = await _use_cases(db).delete_level.execute(
            DeleteLevelCommand(level_id="lv-7", deleted_by="admin-1")
        )

    assert deleted == {"levels": 1, "skills": 2, "criteria": 6}
    assert await db["skill_levels"].count_documents({"academy_id": ACADEMY}) == 1
    assert await db["skills"].count_documents({"academy_id": ACADEMY, "level_id": "lv-7"}) == 0
    assert (
        await db["skill_criteria"].count_documents({"academy_id": ACADEMY, "level_id": "lv-7"}) == 0
    )
    assert (
        await db["skill_criteria"].count_documents({"academy_id": ACADEMY, "level_id": "lv-6"}) == 6
    )
    assert await db["skills"].count_documents({"academy_id": "acad-del-b"}) == 2
    audit = await db["audit_logs"].find_one({"action": "curriculum.level_deleted"})
    assert audit["academy_id"] == ACADEMY and audit["entity_id"] == "lv-7"
    assert audit["actor_id"] == "admin-1" and audit["before"]["skills_deleted"] == 2


@pytest.mark.parametrize(
    ("collection", "row", "label"),
    [
        ("student_level_progress", {"level_id": "lv-7", "status": "ACTIVE"}, "student_placements"),
        (
            "student_skill_progress",
            {"skill_id": "lv-7-s0", "level_id": "lv-7"},
            "skill_progress_rows",
        ),
        ("test_attempts", {"skill_id": "lv-7-s1", "level_id": "lv-7"}, "test_attempts"),
        ("skill_certificates", {"level_id": "lv-7"}, "certificates"),
        (
            "level_up_recommendations",
            {"from_level_id": "lv-6", "to_level_id": "lv-7"},
            "level_up_recommendations",
        ),
        ("coach_skill_notes", {"skill_id": "lv-7-s1"}, "coach_skill_notes"),
        ("external_lesson_refs", {"skill_id": "lv-7-s0"}, "external_refs"),
        ("lesson_cards", {"level_id": "lv-7", "skill_ids": ["lv-7-s0"]}, "lesson_cards"),
        # One recap teaching two of the level's skills counts once.
        ("class_recaps", {"taught_skill_ids": ["lv-7-s0", "lv-7-s1", "other"]}, "class_recaps"),
    ],
)
@pytest.mark.asyncio
async def test_level_in_use_is_refused_and_nothing_is_deleted(db, collection, row, label) -> None:
    await _seed_level(db, "lv-7")
    await db[collection].insert_one({"academy_id": ACADEMY, "student_id": "stu-1", **row})

    with tenant_scope(ACADEMY), pytest.raises(LevelInUse) as exc:
        await _use_cases(db).delete_level.execute(
            DeleteLevelCommand(level_id="lv-7", deleted_by="admin-1")
        )

    assert exc.value.details["in_use"] == {label: 1}
    assert await db["skill_levels"].count_documents({"level_id": "lv-7"}) == 1
    assert await db["skill_criteria"].count_documents({"level_id": "lv-7"}) == 6
    assert await db["audit_logs"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_another_academys_progress_does_not_block_the_delete(db) -> None:
    await _seed_level(db, "lv-7")
    await db["student_skill_progress"].insert_one(
        {"academy_id": "acad-del-b", "skill_id": "lv-7-s0", "level_id": "lv-7"}
    )
    with tenant_scope(ACADEMY):
        usage = await _use_cases(db).get_level_usage.execute("prog-1")
    assert usage == {"lv-7": {}}


def _app(db) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(pathway_router, prefix="/api/v2/admin")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1", email="a@example.com", academy_id=ACADEMY, roles=("admin",)
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        curriculum=_use_cases(db)
    )
    return app


@pytest.mark.asyncio
async def test_routes_report_usage_then_delete_or_refuse_with_409(db) -> None:
    await _seed_level(db, "lv-6")
    await _seed_level(db, "lv-7")
    await db["skill_certificates"].insert_one({"academy_id": ACADEMY, "level_id": "lv-6"})

    transport = httpx.ASGITransport(app=_app(db))
    with tenant_scope(ACADEMY):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            usage = (await client.get("/api/v2/admin/programs/prog-1/level-usage")).json()
            refused = await client.delete("/api/v2/admin/levels/lv-6")
            ok = await client.delete("/api/v2/admin/levels/lv-7")
            missing = await client.delete("/api/v2/admin/levels/lv-7")

    assert usage["levels"]["lv-6"] == {
        "deletable": False,
        "in_use": {"certificates": 1, "later_levels": 1},
    }
    assert usage["levels"]["lv-7"] == {"deletable": True, "in_use": {}}
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "Curriculum.LevelInUse"
    assert "certificates: 1" in refused.json()["error"]["message"]
    assert ok.status_code == 200
    assert ok.json()["deleted"] == {"levels": 1, "skills": 2, "criteria": 6}
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_only_the_last_level_can_go_so_level_up_never_meets_a_gap(db) -> None:
    for level_id in ("lv-6", "lv-7", "lv-8"):
        await _seed_level(db, level_id)
    use_cases = _use_cases(db)

    with tenant_scope(ACADEMY):
        with pytest.raises(LevelInUse) as exc:
            await use_cases.delete_level.execute(
                DeleteLevelCommand(level_id="lv-7", deleted_by="admin-1")
            )
        assert exc.value.details["in_use"] == {"later_levels": 1}
        # Top down works: 8, then 7.
        for level_id in ("lv-8", "lv-7"):
            await use_cases.delete_level.execute(
                DeleteLevelCommand(level_id=level_id, deleted_by="admin-1")
            )
        usage = await use_cases.get_level_usage.execute("prog-1")

    assert usage == {"lv-6": {}}


@pytest.mark.asyncio
async def test_an_inactive_level_in_use_is_still_refused(db) -> None:
    # list_for_program returns active levels only; the guard must not depend on it.
    await _seed_level(db, "lv-7")
    await db["skill_levels"].update_one({"level_id": "lv-7"}, {"$set": {"is_active": False}})
    await db["student_skill_progress"].insert_one(
        {"academy_id": ACADEMY, "skill_id": "lv-7-s0", "level_id": "lv-7"}
    )

    with tenant_scope(ACADEMY), pytest.raises(LevelInUse) as exc:
        await _use_cases(db).delete_level.execute(
            DeleteLevelCommand(level_id="lv-7", deleted_by="admin-1")
        )

    assert exc.value.details["in_use"] == {"skill_progress_rows": 1}
    assert await db["skills"].count_documents({"level_id": "lv-7"}) == 2
