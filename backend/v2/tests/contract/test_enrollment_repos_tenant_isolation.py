"""Tenant-isolation tests per ADR-0006.

Required for every repository: a query under one ``academy_id`` must return
nothing when documents exist only under another.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.domain.self_service import MakeupRequest, OccurrenceRosterEntry
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
    MongoMakeupRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
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
async def test_registration_conflict_lookup_isolates_tenants(db) -> None:
    await db["students"].insert_many(
        [
            {
                "student_id": "student-a",
                "academy_id": "academy-a",
                "parent_id": "parent-1",
                "full_name": "Sam Student",
                "date_of_birth": "2015-05-10",
            },
            {
                "student_id": "student-b",
                "academy_id": "academy-b",
                "parent_id": "parent-1",
                "full_name": "Sam Student",
                "date_of_birth": "2015-05-10",
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "enrollment_id": "enrollment-a",
                "academy_id": "academy-a",
                "session_id": "session-a",
                "student_id": "student-a",
                "status": "active",
            },
            {
                "enrollment_id": "enrollment-b",
                "academy_id": "academy-b",
                "session_id": "session-b",
                "student_id": "student-b",
                "status": "active",
            },
        ]
    )
    repo = MongoStudentRepository(db)

    with tenant_scope("academy-a"):
        student_id = await repo.find_registration_student(
            parent_id="parent-1",
            full_name=" sam   student ",
            date_of_birth="2015-05-10",
        )
        active = await repo.has_active_enrollment(student_id or "")

    assert student_id == "student-a"
    assert active is True


@pytest.mark.asyncio
async def test_registration_lookup_does_not_guess_between_legacy_same_name_children(db) -> None:
    await db["students"].insert_many(
        [
            {
                "student_id": student_id,
                "academy_id": "academy-a",
                "parent_id": "parent-1",
                "full_name": "Sam Student",
            }
            for student_id in ("student-1", "student-2")
        ]
    )
    repo = MongoStudentRepository(db)

    with tenant_scope("academy-a"):
        student_id = await repo.find_registration_student(
            parent_id="parent-1", full_name="Sam Student", date_of_birth=None
        )
        ambiguous = await repo.has_ambiguous_registration_match(
            parent_id="parent-1", full_name="Sam Student", date_of_birth=None
        )

    assert student_id is None
    assert ambiguous is True


@pytest.mark.asyncio
async def test_registration_lookup_allows_new_child_when_known_dobs_differ(db) -> None:
    await db["students"].insert_one(
        {
            "student_id": "student-1",
            "academy_id": "academy-a",
            "parent_id": "parent-1",
            "full_name": "Sam Student",
            "date_of_birth": "2014-01-02",
        }
    )
    repo = MongoStudentRepository(db)

    with tenant_scope("academy-a"):
        student_id = await repo.find_registration_student(
            parent_id="parent-1",
            full_name="Sam Student",
            date_of_birth="2016-03-04",
        )
        ambiguous = await repo.has_ambiguous_registration_match(
            parent_id="parent-1",
            full_name="Sam Student",
            date_of_birth="2016-03-04",
        )

    assert student_id is None
    assert ambiguous is False


@pytest.mark.asyncio
async def test_registration_claim_is_atomic_and_tenant_scoped(db) -> None:
    await db["students"].insert_many(
        [
            {
                "student_id": "student-1",
                "academy_id": academy_id,
                "parent_id": "parent-1",
                "full_name": "Sam Student",
            }
            for academy_id in ("academy-a", "academy-b")
        ]
    )
    repo = MongoStudentRepository(db)

    with tenant_scope("academy-a"):
        first = await repo.claim_registration(
            "student-1",
            "app-a",
            claim_token="token-a",
            claimed_at=datetime(2026, 7, 14, tzinfo=UTC),
            stale_before=datetime(2026, 7, 13, tzinfo=UTC),
        )
        second = await repo.claim_registration(
            "student-1",
            "app-b",
            claim_token="token-b",
            claimed_at=datetime(2026, 7, 14, tzinfo=UTC),
            stale_before=datetime(2026, 7, 13, tzinfo=UTC),
        )
    with tenant_scope("academy-b"):
        other_tenant = await repo.claim_registration(
            "student-1",
            "app-b",
            claim_token="token-b",
            claimed_at=datetime(2026, 7, 14, tzinfo=UTC),
            stale_before=datetime(2026, 7, 13, tzinfo=UTC),
        )

    assert first is True
    assert second is False
    assert other_tenant is True


@pytest.mark.asyncio
async def test_stale_student_registration_claim_can_be_recovered(db, acad) -> None:
    old = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
    now = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    await db["students"].insert_one(
        {
            "student_id": "student-stale",
            "academy_id": acad,
            "parent_id": "parent-1",
            "full_name": "Sam Student",
            "registration_application_id": "abandoned-app",
            "registration_claimed_at": old,
            "registration_claim_token": "expired-token",
        }
    )
    repo = MongoStudentRepository(db)

    recovered = await repo.claim_registration(
        "student-stale",
        "retry-app",
        claim_token="retry-token",
        claimed_at=now,
        stale_before=now - timedelta(minutes=15),
    )

    assert recovered is True
    stored = await db["students"].find_one({"academy_id": acad, "student_id": "student-stale"})
    assert stored is not None
    assert stored["registration_application_id"] == "retry-app"
    await repo.release_registration(
        "student-stale",
        "abandoned-app",
        claim_token="expired-token",
    )
    stored_after_stale_release = await db["students"].find_one(
        {"academy_id": acad, "student_id": "student-stale"}
    )
    assert stored_after_stale_release is not None
    assert stored_after_stale_release["registration_application_id"] == "retry-app"


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


@pytest.mark.asyncio
async def test_absence_notice_repo_isolates_tenants(db) -> None:
    repo = MongoAbsenceNoticeRepository(db)

    with tenant_scope("academy-a"):
        await repo.add(
            AbsenceNotice(
                notice_id="notice-a",
                academy_id="academy-a",
                student_id="student-1",
                occurrence_id="occ-1",
                session_id="session-1",
                submitted_by="parent-1",
                submitted_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
                notice_window_met=True,
            )
        )

    with tenant_scope("academy-b"):
        await repo.add(
            AbsenceNotice(
                notice_id="notice-b",
                academy_id="academy-b",
                student_id="student-1",
                occurrence_id="occ-1",
                session_id="session-1",
                submitted_by="parent-1",
                submitted_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
                notice_window_met=True,
            )
        )

    with tenant_scope("academy-a"):
        rows_a = await repo.list_for_parent("parent-1")
        found_a = await repo.get_for_occurrence_and_student("occ-1", "student-1")

    assert [r.notice_id for r in rows_a] == ["notice-a"]
    assert found_a is not None
    assert found_a.notice_id == "notice-a"

    with tenant_scope("academy-b"):
        rows_b = await repo.list_for_parent("parent-1")

    assert [r.notice_id for r in rows_b] == ["notice-b"]


@pytest.mark.asyncio
async def test_occurrence_roster_repo_isolates_tenants(db) -> None:
    repo = MongoOccurrenceRosterRepository(db)

    with tenant_scope("academy-a"):
        await repo.add(
            OccurrenceRosterEntry(
                entry_id="entry-a",
                academy_id="academy-a",
                occurrence_id="occ-1",
                student_id="student-1",
                source="makeup",
                origin_request_id="req-a",
                created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
            )
        )

    with tenant_scope("academy-b"):
        await repo.add(
            OccurrenceRosterEntry(
                entry_id="entry-b",
                academy_id="academy-b",
                occurrence_id="occ-1",
                student_id="student-1",
                source="trial",
                origin_request_id="req-b",
                created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
            )
        )

    with tenant_scope("academy-a"):
        rows_a = await repo.list_for_occurrence("occ-1")
        exists_a = await repo.exists("occ-1", "student-1")

    assert [r.entry_id for r in rows_a] == ["entry-a"]
    assert exists_a is True

    with tenant_scope("academy-b"):
        rows_b = await repo.list_for_occurrence("occ-1")

    assert [r.entry_id for r in rows_b] == ["entry-b"]

    with tenant_scope("academy-c"):
        exists_c = await repo.exists("occ-1", "student-1")

    assert exists_c is False


@pytest.mark.asyncio
async def test_makeup_request_repo_isolates_tenants(db) -> None:
    repo = MongoMakeupRequestRepository(db)

    with tenant_scope("academy-a"):
        await repo.add(
            MakeupRequest(
                request_id="req-a",
                academy_id="academy-a",
                student_id="student-1",
                parent_id="parent-1",
                missed_occurrence_id="occ-1",
                status="pending",
                expires_at=datetime(2026, 8, 1, tzinfo=UTC),
                created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
            )
        )

    with tenant_scope("academy-b"):
        await repo.add(
            MakeupRequest(
                request_id="req-b",
                academy_id="academy-b",
                student_id="student-1",
                parent_id="parent-1",
                missed_occurrence_id="occ-1",
                status="pending",
                expires_at=datetime(2026, 8, 1, tzinfo=UTC),
                created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
            )
        )

    with tenant_scope("academy-a"):
        rows_a = await repo.list_for_parent("parent-1")
        active_a = await repo.find_active_for_missed_occurrence("occ-1", "student-1")

    assert [r.request_id for r in rows_a] == ["req-a"]
    assert active_a is not None
    assert active_a.request_id == "req-a"

    with tenant_scope("academy-b"):
        rows_b = await repo.list_for_parent("parent-1")

    assert [r.request_id for r in rows_b] == ["req-b"]

    with tenant_scope("academy-c"):
        active_c = await repo.find_active_for_missed_occurrence("occ-1", "student-1")

    assert active_c is None


@pytest.mark.asyncio
async def test_enrollment_repo_active_or_paused_for_student_excludes_ended_rows(db) -> None:
    """Issue #651: the coach authorisation read must see paused enrollments
    (roster seat kept, #641) but never cancelled / withdrawn ones, and only
    within the tenant."""
    await db["enrollments"].insert_many(
        [
            {
                "enrollment_id": f"e-{status}",
                "academy_id": "academy-a",
                "session_id": f"sess-{status}",
                "student_id": "st1",
                "status": status,
            }
            for status in ("active", "paused", "cancelled", "withdrawn")
        ]
        + [
            {
                "enrollment_id": "e-other-tenant",
                "academy_id": "academy-b",
                "session_id": "sess-b",
                "student_id": "st1",
                "status": "active",
            }
        ]
    )
    repo = MongoEnrollmentRepository(db)
    with tenant_scope("academy-a"):
        live = await repo.active_or_paused_for_student("st1")
        active_only = await repo.active_for_student("st1")

    assert sorted(e.session_id for e in live) == ["sess-active", "sess-paused"]
    assert [e.session_id for e in active_only] == ["sess-active"]
