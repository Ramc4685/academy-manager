"""Class recap repositories over a real mongod (migration 0243 applied).

The claims the fakes in tests/unit/test_class_recap.py rely on: one recap per
occurrence (a second first write is refused by the unique index), the
revision compare-and-set refuses a stale write, per-child practice round
trips, reports are insert-only per academy, the owner's handoff list holds
only unresolved owner reports, and the parent read sees only present/late
marks. Tenancy: another academy's rows are invisible.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.coaching.domain.class_recap import ChildPractice, ClassRecap, ClassReport
from backend.v2.contexts.coaching.infrastructure.mongo_class_recap_repo import (
    MongoClassRecapRepository,
    MongoClassReportRepository,
    StudentConfirmedAttendance,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY, OTHER = "acad-recap", "acad-other"
NOW = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)


def _recap(revision: int, **kw: Any) -> ClassRecap:
    base: dict[str, Any] = {
        "recap_id": "rc-1",
        "academy_id": ACADEMY,
        "occurrence_id": "occ-1",
        "session_id": "sess-1",
        "class_starts_at": NOW,
        "taught_skill_ids": ("skill-a", "skill-b"),
        "practice": (
            ChildPractice(student_id="maya", skill_ids=("skill-a",)),
            ChildPractice(student_id="leo", skill_ids=("skill-b",)),
        ),
        "revision": revision,
        "updated_by": "coach-1",
        "updated_at": NOW,
    }
    return ClassRecap(**{**base, **kw})


def _report(report_id: str, outcome: str = "sent_to_owner") -> ClassReport:
    return ClassReport(
        report_id=report_id,
        academy_id=ACADEMY,
        occurrence_id="occ-1",
        class_starts_at=NOW,
        author_id="coach-1",
        text="private words",
        submitted_at=NOW,
        outcome=outcome,  # type: ignore[arg-type]
    )


async def test_one_recap_per_occurrence_with_revision_cas(real_db: Any) -> None:
    repo = MongoClassRecapRepository(real_db)
    with tenant_scope(ACADEMY):
        assert await repo.save(_recap(1), expected_revision=0)
        assert not await repo.save(_recap(1, recap_id="rc-dup"), expected_revision=0)
        stored = await repo.get("occ-1")
        assert stored is not None and stored.practiced_by("leo") == ("skill-b",)
        assert await repo.save(_recap(2, practice=()), expected_revision=1)
        assert not await repo.save(_recap(2), expected_revision=1)  # stale
        assert (await repo.get("occ-1")).practice == ()  # type: ignore[union-attr]
        assert [r.occurrence_id for r in await repo.list_for_occurrences(["occ-1", "x"])] == [
            "occ-1"
        ]
    with tenant_scope(OTHER):
        assert await repo.get("occ-1") is None
        assert await repo.save(_recap(1, academy_id=OTHER), expected_revision=0)


async def test_reports_are_insert_only_and_handoffs_close_once(real_db: Any) -> None:
    repo = MongoClassReportRepository(real_db)
    with tenant_scope(ACADEMY):
        assert await repo.insert(_report("r-1"))
        assert not await repo.insert(_report("r-1"))
        assert await repo.insert(_report("r-2", outcome="applied"))
        assert [r.report_id for r in await repo.list_open_handoffs(limit=10)] == ["r-1"]
        closed = await repo.resolve("r-1", by="owner-1", at=NOW)
        assert closed is not None and closed.resolved_by == "owner-1"
        assert await repo.resolve("r-1", by="owner-1", at=NOW) is None
        assert await repo.list_open_handoffs(limit=10) == []
    with tenant_scope(OTHER):
        assert await repo.get("r-1") is None
        assert await repo.insert(_report("r-1"))  # unique per academy only


async def test_parent_attendance_read_counts_present_and_late_only(real_db: Any) -> None:
    rows = [("occ-1", "present"), ("occ-2", "late"), ("occ-3", "absent"), ("occ-4", "voided")]
    for i, (occurrence_id, status) in enumerate(rows):
        await real_db["attendance"].insert_one(
            {
                "academy_id": ACADEMY,
                "attendance_id": f"a-{i}",
                "occurrence_id": occurrence_id,
                "session_id": "sess-1",
                "student_id": "maya",
                "status": status,
                "marked_by": "coach-1",
                "marked_at": datetime(2026, 11, 1 + i, tzinfo=UTC),
            }
        )
    with tenant_scope(ACADEMY):
        ids = await StudentConfirmedAttendance(real_db).confirmed_occurrence_ids("maya", limit=10)
    assert ids == ["occ-2", "occ-1"]
    with tenant_scope(OTHER):
        assert (
            await StudentConfirmedAttendance(real_db).confirmed_occurrence_ids("maya", limit=10)
            == []
        )


async def test_migration_0243_indexes_back_the_repository_claims(real_db: Any) -> None:
    migration = importlib.import_module("backend.v2.migrations.0243_class_recaps_indexes")
    await migration.up(real_db)  # re-running is a no-op
    recaps = await real_db["class_recaps"].index_information()
    assert recaps["class_recaps_occurrence_uq"]["key"] == [("academy_id", 1), ("occurrence_id", 1)]
    assert recaps["class_recaps_occurrence_uq"]["unique"] is True
    reports = await real_db["class_recap_reports"].index_information()
    assert reports["class_recap_reports_report_uq"]["unique"] is True
    assert reports["class_recap_reports_handoff_idx"]["key"] == [
        ("academy_id", 1),
        ("outcome", 1),
        ("resolved_at", 1),
        ("submitted_at", -1),
    ]
