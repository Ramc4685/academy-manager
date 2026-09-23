"""``programs`` and the per-class public fields are academy-scoped on a real mongod.

Lane B1. The unique ``(academy_id, program_id)`` index is the real one
(migration 0194, applied by the ``real_db`` fixture with every migration),
so two academies may reuse a program id but one academy may not, and no
read or write under academy B ever sees or touches academy A's rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.composition.public_page_admin import compose_admin_public_page
from backend.v2.contexts.enrollment.application.use_cases.programs import CreateProgramCommand
from backend.v2.contexts.enrollment.domain.errors import ProgramNotFound, SessionNotFound
from backend.v2.contexts.enrollment.domain.programs import Program
from backend.v2.contexts.enrollment.infrastructure.mongo_program_repo import (
    MongoProgramRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-contract-riverside"
OTHER = "acad-contract-lakeside"
NOW = datetime(2026, 9, 23, tzinfo=UTC)


def _program(program_id: str, academy_id: str) -> Program:
    return Program(
        program_id=program_id,
        academy_id=academy_id,
        name="Juniors",
        created_at=NOW,
        updated_at=NOW,
    )


async def test_program_id_is_unique_per_academy_not_globally(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        await MongoProgramRepository(real_db).add(_program("p-shared", ACADEMY))
        with pytest.raises(DuplicateKeyError):
            await MongoProgramRepository(real_db).add(_program("p-shared", ACADEMY))
    with tenant_scope(OTHER):
        # Same id in another academy is a different row (#849: never global).
        stored = await MongoProgramRepository(real_db).add(_program("p-shared", OTHER))
        assert stored.academy_id == OTHER


async def test_write_stamps_the_tenant_not_the_callers_academy_id(real_db: Any) -> None:
    with tenant_scope(ACADEMY):
        stored = await MongoProgramRepository(real_db).add(_program("p-forged", OTHER))
    assert stored.academy_id == ACADEMY
    row = await real_db["programs"].find_one({"program_id": "p-forged"})
    assert row["academy_id"] == ACADEMY


async def test_reads_and_writes_from_another_academy_see_nothing(real_db: Any) -> None:
    await real_db["sessions"].insert_one(
        {"academy_id": ACADEMY, "session_id": "sess-a", "title": "Saturday Juniors"}
    )
    with tenant_scope(ACADEMY):
        svc = compose_admin_public_page(real_db)
        program = await svc.create_program.execute(CreateProgramCommand(name="Juniors"))
        await svc.set_class_public_fields.execute("sess-a", {"published": True})
        await svc.assign_class_to_program.execute("sess-a", program.program_id)

    with tenant_scope(OTHER):
        svc = compose_admin_public_page(real_db)
        assert await svc.list_programs.execute(include_archived=True) == []
        assert await svc.list_class_public_profiles.execute() == []
        assert await svc.list_class_public_profiles.execute(published_only=True) == []
        with pytest.raises(ProgramNotFound):
            await svc.update_program.execute(program.program_id, {"name": "Taken"})
        with pytest.raises(ProgramNotFound):
            await svc.archive_program.execute(program.program_id)
        with pytest.raises(SessionNotFound):
            await svc.set_class_public_fields.execute("sess-a", {"published": False})

    row = await real_db["sessions"].find_one({"session_id": "sess-a"})
    assert row["published"] is True
    assert row["program_id"] == program.program_id
    stored = await real_db["programs"].find_one({"program_id": program.program_id})
    assert stored["name"] == "Juniors" and stored["archived"] is False


async def test_published_class_lookup_uses_the_0194_index(real_db: Any) -> None:
    await real_db["sessions"].insert_many(
        [
            {"academy_id": ACADEMY, "session_id": f"s-{i}", "published": i % 2 == 0}
            for i in range(20)
        ]
    )
    plan = await real_db.command(
        {
            "explain": {
                "find": "sessions",
                "filter": {
                    "academy_id": ACADEMY,
                    "published": True,
                    "status": {"$nin": ["cancelled", "completed"]},
                },
            },
            "verbosity": "queryPlanner",
        }
    )
    assert "sessions_academy_published" in str(plan["queryPlanner"]["winningPlan"])
