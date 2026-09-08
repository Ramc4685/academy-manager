"""Mongo-backed admin waiver report contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.infrastructure.mongo_admin_waiver_repo import (
    MongoAdminWaiverRepository,
)

NOW = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


async def _seed_waivers(db, academy_id: str) -> None:
    old = await db["waiver_versions"].insert_one(
        {
            "academy_id": academy_id,
            "version": "2025.1",
            "content_hash": "hash-old",
            "text": "Old waiver",
            "effective_from": NOW - timedelta(days=400),
        }
    )
    current = await db["waiver_versions"].insert_one(
        {
            "academy_id": academy_id,
            "version": "2026.1",
            "content_hash": "hash-current",
            "text": "Current waiver",
            "effective_from": NOW - timedelta(days=30),
        }
    )
    await db["students"].insert_many(
        [
            {
                "academy_id": academy_id,
                "student_id": "st-current",
                "full_name": "Current Student",
                "parent_id": "p-current",
                "status": "active",
            },
            {
                "academy_id": academy_id,
                "student_id": "st-old",
                "first_name": "Old",
                "last_name": "Student",
                "parent_user_id": "p-old",
                "status": "active",
            },
            {
                "academy_id": academy_id,
                "student_id": "st-direct",
                "full_name": "Direct Field Student",
                "parent_id": "p-direct",
                "status": "active",
                "waiver_accepted": True,
                "waiver_version": "2026.1",
                "waiver_text_hash": "hash-current",
                "waiver_accepted_at": NOW - timedelta(days=1),
                "waiver_accepted_by": "p-direct",
            },
            {
                "academy_id": academy_id,
                "student_id": "st-pending",
                "full_name": "Pending Student",
                "parent_id": "p-pending",
                "status": "active",
            },
            {
                "academy_id": "other-academy",
                "student_id": "st-other",
                "full_name": "Other Academy",
                "parent_id": "p-other",
                "status": "active",
            },
        ]
    )
    # issue #651: the report only lists students with a live enrollment.
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": academy_id,
                "enrollment_id": f"enr-{student_id}",
                "session_id": "sess-1",
                "student_id": student_id,
                "status": status,
            }
            for student_id, status in (
                ("st-current", "active"),
                ("st-old", "paused"),
                ("st-direct", "active"),
                ("st-pending", "active"),
                ("st-other", "active"),
            )
        ]
    )
    await db["users"].insert_many(
        [
            {
                "academy_id": academy_id,
                "user_id": "p-current",
                "display_name": "Current Parent",
                "email": "current@example.com",
            },
            {
                "academy_id": academy_id,
                "firebase_uid": "p-old",
                "first_name": "Old",
                "last_name": "Parent",
                "email": "old@example.com",
            },
        ]
    )
    await db["waiver_acceptances"].insert_many(
        [
            {
                "student_id": "st-current",
                "parent_user_id": "p-current",
                "accepted_by_user_id": "p-current",
                "waiver_version_id": str(current.inserted_id),
                "accepted_at": NOW - timedelta(hours=2),
            },
            {
                "student_id": "st-current",
                "parent_user_id": "p-current",
                "accepted_by_user_id": "p-current",
                "waiver_version_id": str(old.inserted_id),
                "accepted_at": NOW - timedelta(days=300),
            },
            {
                "academy_id": academy_id,
                "student_id": "st-old",
                "parent_user_id": "p-old",
                "accepted_by_user_id": "p-old",
                "waiver_version": "2025.1",
                "waiver_text_hash": "hash-old",
                "accepted_at": (NOW - timedelta(days=10)).isoformat(),
            },
            {
                "academy_id": "other-academy",
                "student_id": "st-other",
                "parent_user_id": "p-other",
                "waiver_version": "2026.1",
                "waiver_text_hash": "hash-current",
                "accepted_at": NOW,
            },
        ]
    )


@pytest.mark.asyncio
async def test_load_admin_waiver_data_maps_students_parents_versions_and_latest_acceptances(
    db, acad
) -> None:
    await _seed_waivers(db, acad)
    repo = MongoAdminWaiverRepository(db)

    data = await repo.load_admin_waiver_data()

    assert data.active_waiver is not None
    assert data.active_waiver.version == "2026.1"
    assert [student.student_id for student in data.students] == [
        "st-current",
        "st-direct",
        "st-old",
        "st-pending",
    ]
    current = data.acceptances_by_student["st-current"]
    assert current.waiver_version == "2026.1"
    assert current.content_hash == "hash-current"
    direct = data.acceptances_by_student["st-direct"]
    assert direct.waiver_version == "2026.1"
    assert direct.accepted_by_user_id == "p-direct"
    old_parent = next(s for s in data.students if s.student_id == "st-old")
    assert old_parent.parent_name == "Old Parent"
    assert old_parent.parent_email == "old@example.com"
    assert "st-other" not in data.acceptances_by_student


@pytest.mark.asyncio
async def test_load_admin_waiver_data_returns_truthful_empty_when_no_students(db, acad) -> None:
    repo = MongoAdminWaiverRepository(db)

    data = await repo.load_admin_waiver_data()

    assert data.active_waiver is None
    assert data.students == []
    assert data.acceptances_by_student == {}


@pytest.mark.asyncio
async def test_load_admin_waiver_data_ignores_other_tenant_signatures_for_same_student_id(
    db, acad
) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-current",
            "name": "Current waiver",
            "version": "2026.1",
            "content_hash": "hash-current",
            "body": "Current waiver text",
            "effective_from": NOW,
            "status": "active",
        }
    )
    await db["enrollments"].insert_one(  # issue #651: report needs a live enrollment
        {
            "academy_id": acad,
            "enrollment_id": "enr-shared",
            "session_id": "sess-1",
            "student_id": "shared-student-id",
            "status": "active",
        }
    )
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "shared-student-id",
            "full_name": "Current Tenant Student",
            "parent_id": "p-current",
            "status": "active",
        }
    )
    await db["waiver_signatures"].insert_one(
        {
            "academy_id": "other-academy",
            "waiver_signature_id": "ws-other",
            "waiver_template_id": "wt-current",
            "student_id": "shared-student-id",
            "parent_user_id": "p-other",
            "signed_at": NOW,
            "signer_name": "Other Parent",
            "signer_email": "other@example.com",
            "content_hash": "hash-current",
        }
    )
    repo = MongoAdminWaiverRepository(db)

    data = await repo.load_admin_waiver_data()

    assert data.acceptances_by_student == {}


@pytest.mark.asyncio
async def test_load_admin_waiver_data_includes_share_link_for_signed_rows(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-current",
            "name": "Current waiver",
            "version": "2026.1",
            "content_hash": "hash-current",
            "body": "Current waiver text",
            "effective_from": NOW,
            "status": "active",
        }
    )
    await db["enrollments"].insert_one(  # issue #651: report needs a live enrollment
        {
            "academy_id": acad,
            "enrollment_id": "enr-signed",
            "session_id": "sess-1",
            "student_id": "st-signed",
            "status": "active",
        }
    )
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-signed",
            "full_name": "Signed Student",
            "parent_id": "p-current",
            "status": "active",
        }
    )
    await db["waiver_signatures"].insert_one(
        {
            "academy_id": acad,
            "waiver_signature_id": "ws-signed",
            "waiver_template_id": "wt-current",
            "student_id": "st-signed",
            "parent_user_id": "p-current",
            "signed_at": NOW,
            "signer_name": "Parent One",
            "signer_email": "parent@example.com",
            "content_hash": "hash-current",
            "artifact_id": "wa_ws-signed",
        }
    )
    await db["waiver_share_links"].insert_one(
        {
            "academy_id": acad,
            "share_link_id": "wsl_active_row_link",
            "artifact_id": "wa_ws-signed",
            "signature_id": "ws-signed",
            "status": "active",
            "created_at": NOW,
        }
    )
    repo = MongoAdminWaiverRepository(db)

    data = await repo.load_admin_waiver_data()

    acceptance = data.acceptances_by_student["st-signed"]
    assert acceptance.artifact_id == "wa_ws-signed"
    assert acceptance.share_link_id == "wsl_active_row_link"


@pytest.mark.asyncio
async def test_template_detail_is_tenant_isolated(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": "other-academy",
            "waiver_template_id": "wt-other",
            "name": "Other academy waiver",
            "version": "2026.1",
            "content_hash": "hash-other",
            "body": "Other academy text",
            "effective_from": NOW,
            "status": "active",
        }
    )
    repo = MongoAdminWaiverRepository(db)

    detail = await repo.get_template_detail("wt-other")

    assert detail is None


@pytest.mark.asyncio
async def test_template_detail_includes_registration_assignment_state(db, acad) -> None:
    result = await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "title": "BLNO Liability Waiver",
            "version": "1.0",
            "content_hash": "hash-production",
            "body": "Parent agrees to academy safety rules.",
            "published_at": NOW,
            "updated_at": NOW,
            "status": "published",
            "assigned_to_registration": False,
        }
    )
    repo = MongoAdminWaiverRepository(db)

    detail = await repo.get_template_detail(str(result.inserted_id))

    assert detail is not None
    assert detail.waiver_id == str(result.inserted_id)
    assert detail.status == "active"
    assert detail.assigned_to_registration is False
    assert detail.assigned_at is None


@pytest.mark.asyncio
async def test_signature_detail_is_tenant_isolated(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": "other-academy",
            "waiver_template_id": "wt-other",
            "name": "Other academy waiver",
            "version": "2026.1",
            "content_hash": "hash-other",
            "body": "Other academy text",
            "effective_from": NOW,
            "status": "active",
        }
    )
    await db["waiver_signatures"].insert_one(
        {
            "academy_id": "other-academy",
            "waiver_signature_id": "ws-other",
            "waiver_template_id": "wt-other",
            "student_id": "st-other",
            "parent_user_id": "p-other",
            "signed_at": NOW,
            "signer_name": "Other Parent",
            "signer_email": "other@example.com",
            "content_hash": "hash-other",
        }
    )
    repo = MongoAdminWaiverRepository(db)

    detail = await repo.get_signature_detail("ws-other")

    assert detail is None


@pytest.mark.asyncio
async def test_signature_detail_surfaces_stored_artifact_and_active_share_link(db, acad) -> None:
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "st-1",
            "full_name": "Signed Student",
            "parent_id": "p-1",
            "status": "active",
        }
    )
    await db["users"].insert_one(
        {
            "academy_id": acad,
            "user_id": "p-1",
            "display_name": "Parent One",
            "email": "parent@example.com",
        }
    )
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-1",
            "title": "Annual waiver",
            "version": "2026.1",
            "content_hash": "hash-1",
            "body": "Waiver text",
            "effective_from": NOW,
            "status": "active",
        }
    )
    await db["waiver_signatures"].insert_one(
        {
            "academy_id": acad,
            "waiver_signature_id": "ws-1",
            "waiver_template_id": "wt-1",
            "student_id": "st-1",
            "parent_user_id": "p-1",
            "signed_at": NOW,
            "signer_name": "Parent One",
            "signer_email": "parent@example.com",
            "content_hash": "hash-1",
            "artifact_id": "wa_ws-1",
        }
    )
    await db["waiver_artifacts"].insert_one(
        {
            "academy_id": acad,
            "artifact_id": "wa_ws-1",
            "artifact_type": "signed_waiver",
            "status": "stored",
            "signature_id": "ws-1",
        }
    )
    await db["waiver_share_links"].insert_one(
        {
            "academy_id": acad,
            "share_link_id": "wsl_non_guessable_token_for_test",
            "artifact_id": "wa_ws-1",
            "signature_id": "ws-1",
            "status": "active",
            "created_at": NOW,
        }
    )
    repo = MongoAdminWaiverRepository(db)

    detail = await repo.get_signature_detail("ws-1")

    assert detail is not None
    assert detail.artifact_id == "wa_ws-1"
    assert detail.share_link_id == "wsl_non_guessable_token_for_test"
    assert detail.artifact_status == "stored"
    assert detail.share_status == "available"
    assert "stored" in detail.gap_note


@pytest.mark.asyncio
async def test_load_admin_waiver_data_skips_students_without_a_live_enrollment(db, acad) -> None:
    """Issue #651: a withdrawn / cancelled child must not sit on the admin
    waiver report as "pending signature"; a paused child still does."""
    await _seed_waivers(db, acad)
    await db["students"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": "st-cancelled",
                "full_name": "Cancelled Student",
                "parent_id": "p-cancelled",
                "status": "active",
            },
            {
                "academy_id": acad,
                "student_id": "st-withdrawn",
                "full_name": "Withdrawn Student",
                "parent_id": "p-withdrawn",
                "status": "active",
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "enr-cancelled",
                "session_id": "sess-1",
                "student_id": "st-cancelled",
                "status": "cancelled",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-withdrawn",
                "session_id": "sess-1",
                "student_id": "st-withdrawn",
                "status": "withdrawn",
            },
        ]
    )
    repo = MongoAdminWaiverRepository(db)

    data = await repo.load_admin_waiver_data()

    listed = [student.student_id for student in data.students]
    assert "st-cancelled" not in listed
    assert "st-withdrawn" not in listed
    assert "st-old" in listed  # paused enrollment keeps the child on the report
