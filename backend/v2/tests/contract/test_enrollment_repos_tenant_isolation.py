"""Tenant-isolation tests per ADR-0006.

Required for every repository: a query under one ``academy_id`` must return
nothing when documents exist only under another.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_self_service_policy_repo import (
    MongoSelfServicePolicyRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope


def _session_doc(sid: str, coach_id: str, academy_id: str) -> dict:
    return {
        "session_id": sid,
        "academy_id": academy_id,
        "coach_id": coach_id,
        "title": "X",
        "location": "Court 1",
        "start_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "end_at": datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
        "capacity": 8,
        "status": "scheduled",
    }


@pytest.mark.asyncio
async def test_session_repo_isolates_tenants(db) -> None:
    await db["sessions"].insert_many(
        [
            _session_doc("a-s1", "coach-1", "academy-a"),
            _session_doc("b-s1", "coach-1", "academy-b"),
        ]
    )
    repo = MongoSessionRepository(db)
    with tenant_scope("academy-a"):
        rows = await repo.for_coach_on_date("coach-1", date(2026, 5, 16))
    assert [s.session_id for s in rows] == ["a-s1"]

    with tenant_scope("academy-b"):
        rows = await repo.for_coach_on_date("coach-1", date(2026, 5, 16))
    assert [s.session_id for s in rows] == ["b-s1"]


@pytest.mark.asyncio
async def test_enrollment_repo_isolates_tenants(db) -> None:
    await db["enrollments"].insert_many(
        [
            {
                "enrollment_id": f"{a}-e1",
                "academy_id": a,
                "session_id": "sess",
                "student_id": "st1",
                "status": "active",
            }
            for a in ("academy-a", "academy-b")
        ]
    )
    repo = MongoEnrollmentRepository(db)
    with tenant_scope("academy-a"):
        rows = await repo.active_for_session("sess")
    assert [e.enrollment_id for e in rows] == ["academy-a-e1"]


@pytest.mark.asyncio
async def test_student_repo_isolates_tenants(db) -> None:
    await db["students"].insert_many(
        [
            {
                "student_id": "st1",
                "academy_id": a,
                "parent_id": "p1",
                "full_name": f"Alice-{a}",
            }
            for a in ("academy-a", "academy-b")
        ]
    )
    repo = MongoStudentRepository(db)
    with tenant_scope("academy-a"):
        rows = await repo.by_ids(["st1"])
    assert [s.full_name for s in rows] == ["Alice-academy-a"]


@pytest.mark.asyncio
async def test_self_service_policy_repo_isolates_tenants(db) -> None:
    await db["parent_self_service_policies"].insert_many(
        [
            {"academy_id": "academy-a", "absence_notice_min_hours": 4},
            {"academy_id": "academy-b", "absence_notice_min_hours": 8},
        ]
    )
    repo = MongoSelfServicePolicyRepository(db)

    with tenant_scope("academy-a"):
        policy_a = await repo.get_or_default()
    assert policy_a.academy_id == "academy-a"
    assert policy_a.absence_notice_min_hours == 4

    with tenant_scope("academy-b"):
        policy_b = await repo.get_or_default()
    assert policy_b.academy_id == "academy-b"
    assert policy_b.absence_notice_min_hours == 8


@pytest.mark.asyncio
async def test_self_service_policy_repo_save_does_not_leak_across_tenants(db) -> None:
    repo = MongoSelfServicePolicyRepository(db)

    with tenant_scope("academy-a"):
        await repo.save(
            (await repo.get_or_default()).model_copy(update={"absence_notice_min_hours": 99})
        )

    with tenant_scope("academy-b"):
        policy_b = await repo.get_or_default()
    assert policy_b.absence_notice_min_hours == 2  # default, unaffected by academy-a's save

    with tenant_scope("academy-a"):
        policy_a = await repo.get_or_default()
    assert policy_a.absence_notice_min_hours == 99
