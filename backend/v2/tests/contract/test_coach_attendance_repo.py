"""Mongo coach-attendance repository contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.domain.models import CoachAttendance
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoCoachAttendanceRepository,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _row(**overrides) -> CoachAttendance:
    base = dict(
        attendance_id="coach-att-1",
        academy_id="test-academy",
        occurrence_id="occ-1",
        coach_id="coach-1",
        status="present",
        role="lead",
        source="coach_self",
        marked_by="coach-1",
        marked_at=_dt("2026-05-27T18:05:00"),
        rate_override_minor=None,
        note="",
    )
    base.update(overrides)
    return CoachAttendance(**base)


@pytest.mark.asyncio
async def test_upsert_replaces_occurrence_coach_row(db, acad) -> None:
    repo = MongoCoachAttendanceRepository(db)

    await repo.upsert(_row(status="present", note="checked in"))
    await repo.upsert(
        _row(
            attendance_id="coach-att-2",
            status="absent",
            source="admin",
            marked_by="admin-1",
            note="left early",
        )
    )

    row = await repo.find_for_occurrence_coach("occ-1", "coach-1")

    assert row is not None
    assert row.attendance_id == "coach-att-2"
    assert row.status == "absent"
    assert row.source == "admin"
    assert row.note == "left early"
    assert await db["coach_attendance"].count_documents({"academy_id": acad}) == 1


@pytest.mark.asyncio
async def test_list_for_occurrences_is_tenant_scoped(db, acad, other_acad) -> None:
    repo = MongoCoachAttendanceRepository(db)
    await repo.upsert(_row(attendance_id="coach-att-other", academy_id=other_acad))

    from backend.v2.shared.tenancy.context import _current as _tenant_var

    token = _tenant_var.set(acad)
    try:
        await repo.upsert(_row(attendance_id="coach-att-acad", academy_id=acad))
        rows = await repo.list_for_occurrences(["occ-1"])
    finally:
        _tenant_var.reset(token)

    assert [row.attendance_id for row in rows] == ["coach-att-acad"]
