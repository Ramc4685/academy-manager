"""Contract tests for MongoRegistrationWaiverRepository.

Verifies:
- Assigned-active template resolves to a Waiver domain object.
- Unassigned / non-active / other-tenant templates are NOT resolved.
- Returns None when no assigned-active template exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest

from backend.v2.contexts.onboarding.infrastructure.mongo_registration_waiver_repo import (
    MongoRegistrationWaiverRepository,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
WAIVER_TEXT = "Standard liability waiver body."
CONTENT_HASH = "abc123"


async def _seed_template(
    db,
    *,
    academy_id: str,
    waiver_template_id: str,
    status: str = "active",
    assigned_to_registration: bool = True,
) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": academy_id,
            "waiver_template_id": waiver_template_id,
            "name": "Test Waiver",
            "version": "2026.1",
            "body": WAIVER_TEXT,
            "content_hash": CONTENT_HASH,
            "effective_from": NOW,
            "status": status,
            "assigned_to_registration": assigned_to_registration,
            "assigned_at": NOW,
            "published_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_resolves_assigned_active_template(db, acad):
    await _seed_template(db, academy_id=acad, waiver_template_id="tmpl-1")
    repo = MongoRegistrationWaiverRepository(db)

    waiver = await repo.get_active()

    assert waiver is not None
    assert waiver.waiver_id == "tmpl-1"
    assert waiver.version == "2026.1"
    assert waiver.text == WAIVER_TEXT
    assert waiver.content_hash == CONTENT_HASH
    assert waiver.academy_id == acad


@pytest.mark.asyncio
async def test_resolves_legacy_published_template_shape_from_production(db, acad):
    body = "BLNO Liability Waiver\nParent agrees to academy safety rules."
    result = await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "title": "BLNO Liability Waiver",
            "version": "1.0",
            "body": body,
            "status": "published",
            "published_at": NOW,
            "effective_from": NOW,
            "updated_at": NOW,
        }
    )
    repo = MongoRegistrationWaiverRepository(db)

    waiver = await repo.get_active()

    assert waiver is not None
    assert waiver.waiver_id == str(result.inserted_id)
    assert waiver.version == "1.0"
    assert waiver.text == body
    assert waiver.content_hash == sha256(body.encode("utf-8")).hexdigest()
    assert waiver.academy_id == acad


@pytest.mark.asyncio
async def test_resolves_assigned_legacy_published_template_shape_from_production(db, acad):
    body = "BLNO Liability Waiver\nParent agrees to academy safety rules."
    result = await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "title": "BLNO Liability Waiver",
            "version": "1.0",
            "body": body,
            "status": "published",
            "assigned_to_registration": True,
            "assigned_at": NOW,
            "published_at": NOW,
            "updated_at": NOW,
        }
    )
    repo = MongoRegistrationWaiverRepository(db)

    waiver = await repo.get_active()

    assert waiver is not None
    assert waiver.waiver_id == str(result.inserted_id)
    assert waiver.version == "1.0"
    assert waiver.text == body
    assert waiver.content_hash == sha256(body.encode("utf-8")).hexdigest()
    assert waiver.academy_id == acad


@pytest.mark.asyncio
async def test_returns_none_when_no_assigned_template(db, acad):
    await _seed_template(
        db, academy_id=acad, waiver_template_id="tmpl-unassigned", assigned_to_registration=False
    )
    repo = MongoRegistrationWaiverRepository(db)

    waiver = await repo.get_active()

    assert waiver is None


@pytest.mark.asyncio
async def test_returns_none_for_non_active_status(db, acad):
    await _seed_template(db, academy_id=acad, waiver_template_id="tmpl-draft", status="draft")
    repo = MongoRegistrationWaiverRepository(db)

    waiver = await repo.get_active()

    assert waiver is None


@pytest.mark.asyncio
async def test_tenant_isolation(db, acad):
    # Seed a template for a DIFFERENT tenant directly (no ContextVar switch needed for insert).
    # The acad fixture keeps _current="test-academy" so the repo should not find
    # a document belonging to "other-academy".
    await _seed_template(db, academy_id="other-academy", waiver_template_id="tmpl-other")
    repo = MongoRegistrationWaiverRepository(db)

    waiver = await repo.get_active()

    assert waiver is None


@pytest.mark.asyncio
async def test_returns_none_when_collection_empty(db, acad):
    repo = MongoRegistrationWaiverRepository(db)

    waiver = await repo.get_active()

    assert waiver is None
