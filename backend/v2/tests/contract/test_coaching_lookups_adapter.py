"""Mongo contract tests for ``EnrollmentLookupAdapter.attendance_eligibility``
(issue #672): the composition adapter that tells Coaching whether a student
may be marked on one occurrence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.coaching_lookups import EnrollmentLookupAdapter
from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)


def _enrollment(academy_id: str, session_id: str, student_id: str, status: str) -> dict:
    return {
        "enrollment_id": f"e-{session_id}-{student_id}",
        "academy_id": academy_id,
        "session_id": session_id,
        "student_id": student_id,
        "status": status,
    }


def _entry(occurrence_id: str, student_id: str, source: str = "makeup") -> OccurrenceRosterEntry:
    return OccurrenceRosterEntry(
        entry_id=f"ore-{occurrence_id}-{student_id}",
        academy_id="academy-a",
        occurrence_id=occurrence_id,
        student_id=student_id,
        source=source,  # type: ignore[arg-type]
        origin_request_id="req-1",
        created_at=NOW,
    )


async def _seed(db) -> EnrollmentLookupAdapter:
    await db["enrollments"].insert_many(
        [
            _enrollment("academy-a", "sess-1", "st-active", "active"),
            _enrollment("academy-a", "tmpl-1", "st-template", "active"),
            _enrollment("academy-a", "sess-1", "st-paused", "paused"),
            _enrollment("academy-a", "sess-1", "st-withdrawn", "withdrawn"),
            _enrollment("academy-a", "sess-1", "st-cancelled", "cancelled"),
            # Same ids in another tenant: must never leak across.
            _enrollment("academy-b", "sess-1", "st-other-tenant", "active"),
        ]
    )
    roster = MongoOccurrenceRosterRepository(db)
    with tenant_scope("academy-a"):
        await roster.add(_entry("occ-sat", "st-makeup", "makeup"))
        await roster.add(_entry("occ-sat", "st-trial", "trial"))
        await roster.add(_entry("occ-next-week", "st-makeup-later", "makeup"))
        # A paused family whose make-up was approved for this occurrence
        # before the pause: the roster row still exists (past-dated cleanup
        # only removes future rows), but it is for the occurrence itself.
    with tenant_scope("academy-b"):
        await roster.add(
            OccurrenceRosterEntry(
                entry_id="ore-b",
                academy_id="academy-b",
                occurrence_id="occ-sat",
                student_id="st-b-makeup",
                source="makeup",
                origin_request_id="req-b",
                created_at=NOW,
            )
        )
    return EnrollmentLookupAdapter(MongoEnrollmentRepository(db), roster)


async def _eligibility(adapter, student_id: str, *, occurrence_id: str = "occ-sat"):
    return await adapter.attendance_eligibility(
        occurrence_id=occurrence_id,
        session_id="sess-1",
        template_session_id="tmpl-1",
        student_id=student_id,
    )


@pytest.mark.asyncio
async def test_active_enrollment_in_session_or_template_is_enrollment_source(db) -> None:
    adapter = await _seed(db)
    with tenant_scope("academy-a"):
        direct = await _eligibility(adapter, "st-active")
        via_template = await _eligibility(adapter, "st-template")
    assert direct is not None and direct.source == "enrollment"
    assert via_template is not None and via_template.source == "enrollment"


@pytest.mark.asyncio
async def test_approved_makeup_or_trial_entry_on_this_occurrence_is_eligible(db) -> None:
    adapter = await _seed(db)
    with tenant_scope("academy-a"):
        makeup = await _eligibility(adapter, "st-makeup")
        trial = await _eligibility(adapter, "st-trial")
    assert makeup is not None and makeup.source == "makeup"
    assert trial is not None and trial.source == "trial"


@pytest.mark.asyncio
async def test_makeup_entry_on_a_different_occurrence_is_not_eligible(db) -> None:
    adapter = await _seed(db)
    with tenant_scope("academy-a"):
        here = await _eligibility(adapter, "st-makeup-later")
        there = await _eligibility(adapter, "st-makeup-later", occurrence_id="occ-next-week")
    assert here is None
    assert there is not None and there.source == "makeup"


@pytest.mark.asyncio
async def test_paused_withdrawn_cancelled_and_unknown_students_are_not_eligible(db) -> None:
    adapter = await _seed(db)
    with tenant_scope("academy-a"):
        for student_id in ("st-paused", "st-withdrawn", "st-cancelled", "st-ghost"):
            assert await _eligibility(adapter, student_id) is None, student_id


@pytest.mark.asyncio
async def test_eligibility_never_crosses_tenants(db) -> None:
    adapter = await _seed(db)
    with tenant_scope("academy-a"):
        assert await _eligibility(adapter, "st-other-tenant") is None
        assert await _eligibility(adapter, "st-b-makeup") is None
    with tenant_scope("academy-b"):
        b = await _eligibility(adapter, "st-b-makeup")
        assert b is not None and b.source == "makeup"
        assert await _eligibility(adapter, "st-makeup") is None
