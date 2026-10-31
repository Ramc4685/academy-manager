"""Waiver lifecycle gaps from #785.

Two orphans, both reproduced here before the fix:

* Publishing a new template version superseded the row that carried
  ``assigned_to_registration`` and never moved the flag onto the new version,
  so ``get_registration_template`` found nothing and registration silently
  stopped asking anyone to sign.
* The registration read and the parent prompt disagreed about which statuses
  count as live (``active``/``published`` vs ``active`` only), so a production
  row spelled ``published`` was required at registration and invisible to the
  parent who had to sign it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
    MongoParentWaiverRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_template_repo import (
    MongoWaiverTemplateRepository,
)

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_publish_draft_carries_the_registration_assignment_forward(db, acad) -> None:
    await db["waiver_templates"].insert_many(
        [
            {
                "academy_id": acad,
                "waiver_template_id": "wt-live",
                "name": "2025 waiver",
                "body": "old text",
                "status": "active",
                "version": "2025.1",
                "content_hash": "hash-2025",
                "effective_from": NOW,
                "updated_at": NOW,
                "assigned_to_registration": True,
                "assigned_at": NOW,
            },
            {
                "academy_id": acad,
                "waiver_template_id": "wt-draft",
                "name": "2026 waiver",
                "body": "new text",
                "status": "draft",
                "updated_at": NOW,
            },
        ]
    )
    repo = MongoWaiverTemplateRepository(db)

    published = await repo.publish_draft(
        waiver_template_id="wt-draft",
        version="2026.1",
        content_hash="hash-2026",
        published_at=LATER,
    )

    assert published.assigned_to_registration is True
    registration = await repo.get_registration_template()
    assert registration is not None
    assert registration.waiver_template_id == "wt-draft"
    superseded = await db["waiver_templates"].find_one(
        {"academy_id": acad, "waiver_template_id": "wt-live"}
    )
    assert superseded is not None
    assert superseded["status"] == "superseded"
    # Exactly one row may claim the registration slot, or the "most recently
    # assigned" sort decides which version families sign by accident.
    assert superseded["assigned_to_registration"] is False


@pytest.mark.asyncio
async def test_publish_draft_leaves_registration_unassigned_when_nothing_claimed_it(
    db, acad
) -> None:
    await db["waiver_templates"].insert_many(
        [
            {
                "academy_id": acad,
                "waiver_template_id": "wt-live",
                "name": "2025 waiver",
                "body": "old text",
                "status": "active",
                "version": "2025.1",
                "content_hash": "hash-2025",
                "effective_from": NOW,
                "updated_at": NOW,
            },
            {
                "academy_id": acad,
                "waiver_template_id": "wt-draft",
                "name": "2026 waiver",
                "body": "new text",
                "status": "draft",
                "updated_at": NOW,
            },
        ]
    )
    repo = MongoWaiverTemplateRepository(db)

    published = await repo.publish_draft(
        waiver_template_id="wt-draft",
        version="2026.1",
        content_hash="hash-2026",
        published_at=LATER,
    )

    assert published.assigned_to_registration is False
    assert await repo.get_registration_template() is None


@pytest.mark.asyncio
async def test_publish_draft_does_not_inherit_another_academys_assignment(db, acad) -> None:
    await db["waiver_templates"].insert_many(
        [
            {
                "academy_id": "other-academy",
                "waiver_template_id": "wt-other",
                "name": "Other academy waiver",
                "body": "other",
                "status": "active",
                "version": "2025.1",
                "content_hash": "hash-other",
                "effective_from": NOW,
                "updated_at": NOW,
                "assigned_to_registration": True,
                "assigned_at": NOW,
            },
            {
                "academy_id": acad,
                "waiver_template_id": "wt-draft",
                "name": "2026 waiver",
                "body": "new text",
                "status": "draft",
                "updated_at": NOW,
            },
        ]
    )
    repo = MongoWaiverTemplateRepository(db)

    published = await repo.publish_draft(
        waiver_template_id="wt-draft",
        version="2026.1",
        content_hash="hash-2026",
        published_at=LATER,
    )

    assert published.assigned_to_registration is False
    other = await db["waiver_templates"].find_one(
        {"academy_id": "other-academy", "waiver_template_id": "wt-other"}
    )
    assert other is not None
    assert other["status"] == "active"
    assert other["assigned_to_registration"] is True


@pytest.mark.asyncio
async def test_parent_prompt_and_registration_read_agree_on_a_published_row(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-prod",
            "name": "BLNO Liability Waiver",
            "body": "Parent agrees to academy safety rules.",
            # The production spelling. `get_registration_template` accepted it
            # and the parent prompt did not, so the waiver was required and
            # unsignable at the same time.
            "status": "published",
            "version": "1.0",
            "content_hash": "hash-prod",
            "published_at": NOW,
            "updated_at": NOW,
            "assigned_to_registration": True,
            "assigned_at": NOW,
        }
    )

    registration = await MongoWaiverTemplateRepository(db).get_registration_template()
    prompt = await MongoParentWaiverRepository(db).get_required_template()

    assert registration is not None
    assert prompt is not None
    assert prompt.waiver_template_id == registration.waiver_template_id
