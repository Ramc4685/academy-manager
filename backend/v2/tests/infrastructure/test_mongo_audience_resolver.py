"""Mongo audience resolver membership lookups."""

from __future__ import annotations

from backend.v2.contexts.communications.domain.models import AcademyAudience
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.shared.tenancy.context import tenant_scope
from mongomock_motor import AsyncMongoMockClient


async def test_academy_coach_audience_uses_active_memberships_for_global_users() -> None:
    db = AsyncMongoMockClient()["audience-resolver-memberships"]
    await db["users"].insert_many(
        [
            {
                "user_id": "coach-1",
                "email": "coach@example.com",
                "display_name": "Coach One",
            },
            {
                "user_id": "parent-1",
                "email": "parent@example.com",
                "display_name": "Parent One",
            },
            {
                "user_id": "inactive-coach",
                "email": "inactive@example.com",
                "display_name": "Inactive Coach",
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "user_id": "coach-1",
                "roles": ["coach"],
                "status": "active",
            },
            {
                "academy_id": "acad-1",
                "user_id": "parent-1",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "acad-1",
                "user_id": "inactive-coach",
                "roles": ["coach"],
                "status": "inactive",
            },
            {
                "academy_id": "acad-2",
                "user_id": "other-coach",
                "roles": ["coach"],
                "status": "active",
            },
        ]
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_academy_audience(
            AcademyAudience(role="coach")
        )

    assert [recipient.user_id for recipient in recipients] == ["coach-1"]
    assert recipients[0].email == "coach@example.com"
