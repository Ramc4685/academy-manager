"""Migration 0165 — every existing admin membership becomes an owner too.

The owner/admin split would otherwise strip refunds, pricing, payouts,
reports and audit from the people running academies today.
"""

from __future__ import annotations

import importlib

import mongomock_motor
from bson import ObjectId


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module("backend.v2.migrations.0165_grant_owner_to_existing_admins")
    await mod.up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed(db) -> None:  # type: ignore[no-untyped-def]
    await db.academy_memberships.insert_many(
        [
            {
                "membership_id": "m-admin",
                "academy_id": "acad",
                "user_id": "u-admin",
                "roles": ["admin"],
            },
            {
                "membership_id": "m-coach",
                "academy_id": "acad",
                "user_id": "u-coach",
                "roles": ["coach"],
            },
        ]
    )
    await db.users.insert_many(
        [
            {"academy_id": "acad", "user_id": "u-admin", "role": "admin", "roles": ["admin"]},
            {"academy_id": "acad", "user_id": "u-coach", "role": "coach", "roles": ["coach"]},
        ]
    )


async def _roles(db, collection: str, user_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    doc = await db[collection].find_one({"user_id": user_id})
    assert doc is not None
    return list(doc.get("roles") or [])


async def test_only_admin_memberships_gain_owner() -> None:
    db = _fresh_db()
    await _seed(db)

    await _run(db)

    assert await _roles(db, "academy_memberships", "u-admin") == ["admin", "owner"]
    assert await _roles(db, "academy_memberships", "u-coach") == ["coach"]


async def test_owner_is_mirrored_into_the_legacy_users_doc() -> None:
    db = _fresh_db()
    await _seed(db)

    await _run(db)

    assert await _roles(db, "users", "u-admin") == ["admin", "owner"]
    assert await _roles(db, "users", "u-coach") == ["coach"]
    admin = await db.users.find_one({"user_id": "u-admin"})
    assert admin is not None
    assert admin["role"] == "admin", "the legacy primary role field is left alone"


async def test_is_idempotent() -> None:
    db = _fresh_db()
    await _seed(db)

    await _run(db)
    await _run(db)

    assert await _roles(db, "academy_memberships", "u-admin") == ["admin", "owner"]
    assert await _roles(db, "users", "u-admin") == ["admin", "owner"]


async def test_an_admin_who_is_already_an_owner_is_untouched() -> None:
    db = _fresh_db()
    await db.academy_memberships.insert_one(
        {"academy_id": "acad", "user_id": "u-both", "roles": ["owner", "admin"], "updated_at": "t0"}
    )
    await db.users.insert_one(
        {"academy_id": "acad", "user_id": "u-both", "roles": ["owner", "admin"]}
    )

    await _run(db)

    membership = await db.academy_memberships.find_one({"user_id": "u-both"})
    assert membership is not None
    assert membership["roles"] == ["owner", "admin"]
    assert membership["updated_at"] == "t0"


async def test_users_doc_with_only_the_legacy_role_field_keeps_admin() -> None:
    """Pre-`roles` directory docs must not collapse to just `["owner"]`."""
    db = _fresh_db()
    oid = ObjectId()
    await db.academy_memberships.insert_one(
        {"academy_id": "acad", "user_id": str(oid), "roles": ["admin"]}
    )
    await db.users.insert_one({"_id": oid, "academy_id": "acad", "role": "admin"})

    await _run(db)

    doc = await db.users.find_one({"_id": oid})
    assert doc is not None
    assert doc["roles"] == ["admin", "owner"]


async def test_mirror_is_scoped_to_the_membership_academy() -> None:
    """The same user in another academy must not become an owner there."""
    db = _fresh_db()
    await db.academy_memberships.insert_one(
        {"academy_id": "acad-a", "user_id": "u-1", "roles": ["admin"]}
    )
    await db.users.insert_many(
        [
            {"academy_id": "acad-a", "user_id": "u-1", "roles": ["admin"]},
            {"academy_id": "acad-b", "user_id": "u-1", "roles": ["admin"]},
        ]
    )

    await _run(db)

    a = await db.users.find_one({"academy_id": "acad-a", "user_id": "u-1"})
    b = await db.users.find_one({"academy_id": "acad-b", "user_id": "u-1"})
    assert a is not None and a["roles"] == ["admin", "owner"]
    assert b is not None and b["roles"] == ["admin"]
