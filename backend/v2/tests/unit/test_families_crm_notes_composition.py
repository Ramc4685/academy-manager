"""``composition/families_crm.py`` wires family notes and follow-ups, and the
follow-up assignee check is identity's membership row for THIS academy."""

from __future__ import annotations

from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.families_crm import (
    _MembershipStaffDirectory,
    compose_admin_family_index,
)


async def test_compose_attaches_notes_and_follow_ups() -> None:
    services = compose_admin_family_index(AsyncMongoMockClient()["t"])
    assert services.notes is not None and services.follow_ups is not None
    assert services.follow_ups.queue is not None


async def test_only_active_admin_or_owner_members_of_this_academy_are_staff() -> None:
    db = AsyncMongoMockClient()["t"]
    await db["users"].insert_many(
        [
            {"user_id": "u-admin", "firebase_uid": "fb-admin", "email": "a@example.test"},
            {"user_id": "u-parent", "email": "p@example.test"},
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            # Keyed by the firebase alias: still the same person.
            {"academy_id": "acad-a", "user_id": "fb-admin", "roles": ["admin"], "status": "active"},
            {
                "academy_id": "acad-a",
                "user_id": "u-parent",
                "roles": ["parent"],
                "status": "active",
            },
            {"academy_id": "acad-a", "user_id": "u-gone", "roles": ["owner"], "status": "removed"},
        ]
    )
    staff = _MembershipStaffDirectory(db)
    assert await staff.is_staff("acad-a", "u-admin") is True
    assert await staff.is_staff("acad-b", "u-admin") is False
    assert await staff.is_staff("acad-a", "u-parent") is False
    assert await staff.is_staff("acad-a", "u-gone") is False
    assert await staff.is_staff("acad-a", "nobody") is False
