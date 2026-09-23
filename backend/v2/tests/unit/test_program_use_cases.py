"""Programs CRUD, class assignment and per-class public fields (Lane B1).

Run over the real Mongo repositories on mongomock with migration 0194
applied, so the unique ``(academy_id, program_id)`` index, the tenant filter
and the targeted ``$set``/``$unset`` are the store's, not a fake's. The
cross-academy guarantees are asked again of a real mongod in
``contract/test_programs_are_academy_scoped.py``.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import mongomock_motor
import pytest

from backend.v2.composition.public_page_admin import compose_admin_public_page
from backend.v2.contexts.enrollment.application.use_cases.programs import (
    CreateProgramCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    InvalidClassPublicFields,
    InvalidProgram,
    ProgramNotFound,
    SessionNotFound,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.shared.tenancy import tenant_scope

_M0194 = importlib.import_module("backend.v2.migrations.0194_programs")

ACADEMY = "acad-riverside"
OTHER = "acad-lakeside"
T0 = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)


async def _db() -> Any:
    db = mongomock_motor.AsyncMongoMockClient()["programs_use_cases"]
    await _M0194.up(db)
    # A legacy class row: none of the public keys exist on it.
    await db["sessions"].insert_one(
        {
            "academy_id": ACADEMY,
            "session_id": "sess-juniors",
            "title": "Saturday Juniors",
            "coach_id": "coach-1",
            "location": "Riverside Hall",
            "start_at": T0,
            "end_at": T0.replace(hour=16),
            "capacity": 12,
            "status": "scheduled",
        }
    )
    await db["sessions"].insert_one(
        {"academy_id": OTHER, "session_id": "sess-other", "title": "Lakeside Adults"}
    )
    return db


async def test_create_list_update_archive_program() -> None:
    db = await _db()
    svc = compose_admin_public_page(db)
    with tenant_scope(ACADEMY):
        first = await svc.create_program.execute(
            CreateProgramCommand(
                name=" Juniors ",
                level="Beginner",
                age_band={"min_age": 6, "max_age": 9},
                public_description="Footwork and fun.",
            )
        )
        second = await svc.create_program.execute(CreateProgramCommand(name="Adults"))
        assert first.name == "Juniors"
        assert first.academy_id == ACADEMY
        assert (first.sort_order, second.sort_order) == (0, 1)  # appended in order

        renamed = await svc.update_program.execute(
            first.program_id, {"name": "Junior Squad", "sort_order": 5, "level": None}
        )
        assert renamed.name == "Junior Squad"
        assert renamed.level is None
        assert renamed.age_band is not None and renamed.age_band.min_age == 6
        assert renamed.public_description == "Footwork and fun."  # untouched key kept

        listed = await svc.list_programs.execute()
        assert [p.name for p in listed] == ["Adults", "Junior Squad"]

        archived = await svc.archive_program.execute(second.program_id)
        assert archived.archived is True
        assert [p.name for p in await svc.list_programs.execute()] == ["Junior Squad"]
        assert len(await svc.list_programs.execute(include_archived=True)) == 2

    row = await db["programs"].find_one({"program_id": first.program_id})
    assert row["academy_id"] == ACADEMY


async def test_invalid_program_input_is_a_422_domain_error() -> None:
    svc = compose_admin_public_page(await _db())
    with tenant_scope(ACADEMY):
        with pytest.raises(InvalidProgram):
            await svc.create_program.execute(CreateProgramCommand(name="  "))
        with pytest.raises(InvalidProgram):
            await svc.create_program.execute(
                CreateProgramCommand(name="Teens", age_band={"min_age": 15, "max_age": 12})
            )
        program = await svc.create_program.execute(CreateProgramCommand(name="Teens"))
        with pytest.raises(InvalidProgram):
            await svc.update_program.execute(program.program_id, {"name": None})
        with pytest.raises(InvalidProgram):
            await svc.update_program.execute(program.program_id, {"academy_id": OTHER})
        with pytest.raises(InvalidProgram):
            await svc.update_program.execute(program.program_id, {"archived": "yes"})
        with pytest.raises(ProgramNotFound):
            await svc.update_program.execute("no-such-program", {"name": "X"})


async def test_existing_class_is_private_until_switched_on() -> None:
    db = await _db()
    svc = compose_admin_public_page(db)
    with tenant_scope(ACADEMY):
        [profile] = await svc.list_class_public_profiles.execute()
        assert profile.session_id == "sess-juniors"
        assert profile.published is False
        assert profile.coach_display == "full_name"
        assert profile.price_period is None
        assert profile.effective_price_period() == "month"
        assert await svc.list_class_public_profiles.execute(published_only=True) == []

        updated = await svc.set_class_public_fields.execute(
            "sess-juniors",
            {
                "published": True,
                "price_period": "term",
                "coach_display": "first_name",
                "age_band": {"min_age": 6, "max_age": 9},
                "level": "Beginner",
            },
        )
        assert updated.published is True
        assert updated.price_period == "term"
        assert updated.coach_display == "first_name"
        published = await svc.list_class_public_profiles.execute(published_only=True)
        assert [p.session_id for p in published] == ["sess-juniors"]

        # Partial: resetting the period leaves the switch alone.
        reset = await svc.set_class_public_fields.execute("sess-juniors", {"price_period": None})
        assert reset.price_period is None
        assert reset.published is True

    row = await db["sessions"].find_one({"session_id": "sess-juniors"})
    assert "price_period" not in row  # null unsets, so the academy default applies
    assert row["age_band"] == {"min_age": 6, "max_age": 9}


async def test_an_ordinary_class_edit_never_resets_the_public_fields() -> None:
    db = await _db()
    svc = compose_admin_public_page(db)
    with tenant_scope(ACADEMY):
        await svc.set_class_public_fields.execute("sess-juniors", {"published": True})
        writer = MongoSessionWriter(db)
        session = await writer.get("sess-juniors")
        assert isinstance(session, Session)
        await writer.update(session.model_copy(update={"title": "Saturday Juniors (new)"}))
        profile = (await svc.list_class_public_profiles.execute())[0]
        assert profile.published is True


@pytest.mark.parametrize(
    "changes",
    [
        {"published": "true"},
        {"published": None},
        {"price_period": "week"},
        {"coach_display": "initials"},
        {"coach_display": None},
        {"age_band": {"min_age": 9, "max_age": 6}},
        {"program_id": "p-1"},  # assignment has its own use case
        {"title": "renamed"},
    ],
)
async def test_invalid_class_public_fields_are_refused(changes: dict[str, Any]) -> None:
    db = await _db()
    svc = compose_admin_public_page(db)
    with tenant_scope(ACADEMY):
        with pytest.raises(InvalidClassPublicFields):
            await svc.set_class_public_fields.execute("sess-juniors", changes)
    row = await db["sessions"].find_one({"session_id": "sess-juniors"})
    assert "published" not in row


async def test_assign_class_to_program_and_clear_it() -> None:
    db = await _db()
    svc = compose_admin_public_page(db)
    with tenant_scope(ACADEMY):
        program = await svc.create_program.execute(CreateProgramCommand(name="Juniors"))
        assigned = await svc.assign_class_to_program.execute("sess-juniors", program.program_id)
        assert assigned.program_id == program.program_id
        cleared = await svc.assign_class_to_program.execute("sess-juniors", None)
        assert cleared.program_id is None

        archived = await svc.create_program.execute(CreateProgramCommand(name="Old"))
        await svc.archive_program.execute(archived.program_id)
        with pytest.raises(ProgramNotFound):
            await svc.assign_class_to_program.execute("sess-juniors", archived.program_id)
        with pytest.raises(ProgramNotFound):
            await svc.assign_class_to_program.execute("sess-juniors", "no-such-program")
        with pytest.raises(SessionNotFound):
            await svc.assign_class_to_program.execute("no-such-class", program.program_id)


async def test_another_academys_class_and_program_are_not_found() -> None:
    db = await _db()
    svc = compose_admin_public_page(db)
    with tenant_scope(OTHER):
        foreign = await svc.create_program.execute(CreateProgramCommand(name="Lakeside"))
    with tenant_scope(ACADEMY):
        with pytest.raises(SessionNotFound):
            await svc.set_class_public_fields.execute("sess-other", {"published": True})
        with pytest.raises(ProgramNotFound):
            await svc.assign_class_to_program.execute("sess-juniors", foreign.program_id)
        with pytest.raises(ProgramNotFound):
            await svc.update_program.execute(foreign.program_id, {"name": "Stolen"})
        assert await svc.list_programs.execute(include_archived=True) == []
    other_row = await db["sessions"].find_one({"session_id": "sess-other"})
    assert "published" not in other_row
