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
