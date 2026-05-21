"""Identity membership and platform role indexes.

Creates the indexes required by ADR-0007 for the global identity model:

  users:
    - unique(firebase_uid)       sparse — legacy rows may lack this field
    - unique(normalized_email)   sparse — legacy rows may lack this field

  academy_memberships:
    - unique(academy_id, user_id)           one row per user per academy
    - index(user_id, status)                list all academies for a user
    - index(academy_id, roles, status)      role-filtered member lists

  platform_roles:
    - unique(user_id, role)                 one grant per role per user
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0080_identity_membership_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    users = db["users"]
    await users.create_index(
        "firebase_uid",
        unique=True,
        sparse=True,
        name="users_firebase_uid_unique",
    )
    await users.create_index(
        "normalized_email",
        unique=True,
        sparse=True,
        name="users_normalized_email_unique",
    )

    memberships = db["academy_memberships"]
    await memberships.create_index(
        [("academy_id", 1), ("user_id", 1)],
        unique=True,
        name="membership_academy_user_unique",
    )
    await memberships.create_index(
        [("user_id", 1), ("status", 1)],
        name="membership_user_status",
    )
    await memberships.create_index(
        [("academy_id", 1), ("roles", 1), ("status", 1)],
        name="membership_academy_roles_status",
    )

    platform_roles = db["platform_roles"]
    await platform_roles.create_index(
        [("user_id", 1), ("role", 1)],
        unique=True,
        name="platform_role_user_role_unique",
    )
