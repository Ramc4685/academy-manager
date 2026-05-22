"""Contract tests for Mongo tenant bootstrap persistence."""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
    BootstrapAcademyCommand,
)
from backend.v2.contexts.identity.infrastructure.mongo_bootstrap_store import (
    MongoTenantBootstrapStore,
)


def _command() -> BootstrapAcademyCommand:
    return BootstrapAcademyCommand(
        display_name="North Shore Badminton",
        slug="north-shore",
        primary_domain="north.example.com",
        owner_email="owner@example.com",
        owner_display_name="Owner One",
        timezone="America/Chicago",
    )


@pytest.mark.asyncio
async def test_mongo_bootstrap_store_creates_idempotent_tenant_defaults(db) -> None:
    use_case = BootstrapAcademy(
        store=MongoTenantBootstrapStore(db),
        id_factory=lambda prefix: f"{prefix}test",
    )

    first = await use_case.execute(_command())
    second = await use_case.execute(_command())

    assert first.created is True
    assert second.created is False
    assert first.academy_id == second.academy_id

    academy = await db["academies"].find_one({"academy_id": first.academy_id})
    assert academy is not None
    assert academy["slug"] == "north-shore"
    assert academy["primary_domain"] == "north.example.com"
    assert academy["custom_domain"] == "north.example.com"

    owner = await db["users"].find_one({"normalized_email": "owner@example.com"})
    assert owner is not None
    assert "academy_id" not in owner
    assert "roles" not in owner

    membership = await db["academy_memberships"].find_one(
        {"academy_id": first.academy_id, "user_id": owner["user_id"]}
    )
    assert membership is not None
    assert membership["roles"] == ["admin"]

    assert await db["academy_settings"].count_documents({"academy_id": first.academy_id}) == 1
    assert await db["billing_policies"].count_documents({"academy_id": first.academy_id}) == 1
    assert await db["waiver_templates"].count_documents({"academy_id": first.academy_id}) == 1
    assert await db["academy_roles"].count_documents({"academy_id": first.academy_id}) == 3
    assert await db["academy_feature_flags"].count_documents({"academy_id": first.academy_id}) == 1
