"""Contract coverage for parent waiver acceptance against production data shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    PatchApplication,
    PatchApplicationCommand,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_registration_waiver_repo import (
    MongoRegistrationWaiverRepository,
)

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_parent_can_accept_production_published_registration_waiver(db, acad):
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
    await db["onboarding_applications"].insert_one(
        {
            "academy_id": acad,
            "application_id": "app-prod-waiver",
            "parent_user_id": "parent-1",
            "parent_email": "parent@example.com",
            "status": "DRAFT",
            "parent_profile": {},
            "child_profile": {},
            "expires_at": NOW + timedelta(days=7),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    use_case = PatchApplication(
        apps=MongoApplicationRepository(db),
        waivers=MongoRegistrationWaiverRepository(db),
        clock=lambda: NOW,
    )

    app = await use_case.execute(
        PatchApplicationCommand(
            application_id="app-prod-waiver",
            caller_user_id="parent-1",
            accept_waiver=True,
        )
    )

    assert app.waiver_acceptance is not None
    assert app.waiver_acceptance.waiver_version == "1.0"
    assert app.waiver_acceptance.content_hash == sha256(body.encode("utf-8")).hexdigest()
    assert app.waiver_acceptance.waiver_template_id == str(result.inserted_id)

    stored = await db["onboarding_applications"].find_one(
        {"academy_id": acad, "application_id": "app-prod-waiver"}
    )
    assert stored is not None
    stored_acceptance = stored["waiver_acceptance"]
    assert stored_acceptance["waiver_template_id"] == str(result.inserted_id)
    assert stored_acceptance["waiver_version"] == "1.0"
    assert stored_acceptance["content_hash"] == sha256(body.encode("utf-8")).hexdigest()
    assert stored_acceptance["accepted_at"].replace(tzinfo=UTC) == NOW
