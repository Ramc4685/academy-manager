"""Staff role assignment on the real store (#553, roadmap L2c).

The Staff page grants and revokes owner, admin, billing, front desk and coach
through ``MongoUserRepository``. On a real ``mongod`` with every migration
replayed (the 0132 membership validator included) this pins:

* a staff-tier grant lands on the membership auth reads and writes one audit
  row naming the actor, the reason and the before/after roles;
* the academy can never lose its last live owner, whichever door is used:
  removing the role, replacing every role, or disabling the account. An
  invited or suspended owner does not count as a live one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.domain.errors import CannotRemoveLastOwner
from backend.v2.contexts.identity.infrastructure import mongo_user_repo as user_repo_module
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

ACADEMY = "acad-staff"
OTHER_ACADEMY = "acad-other"


async def _seed(
    db: Any,
    user_id: str,
    roles: list[str],
    *,
    academy_id: str = ACADEMY,
    membership_status: str = "active",
) -> None:
    now = datetime.now(UTC)
    await db["users"].insert_one(
        {
            "user_id": user_id,
            "email": f"{user_id}@example.com",
            "display_name": f"Test {user_id}",
            "role": roles[0],
            "roles": roles,
            "status": "active",
            "academy_id": academy_id,
            "created_at": now,
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": f"m-{academy_id}-{user_id}",
            "academy_id": academy_id,
            "user_id": user_id,
            "roles": roles,
            "status": membership_status,
            "created_at": now,
        }
    )


def _repo(db: Any) -> MongoUserRepository:
    return MongoUserRepository(db, default_academy_id=ACADEMY)


class _NoFirebase:
    async def set_user_disabled(self, uid: str, disabled: bool) -> None:
        _ = (uid, disabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["billing", "front_desk"])
async def test_granting_a_staff_tier_updates_membership_and_writes_audit(
    real_db: Any, role: str
) -> None:
    await _seed(real_db, "u-owner", ["owner", "admin"])
    await _seed(real_db, "u-staff", ["coach"])

    detail = await _repo(real_db).add_role(
        "u-staff", role, academy_id=ACADEMY, actor_id="u-owner", reason="New hire"
    )

    assert detail is not None and set(detail.roles) == {"coach", role}
    membership = await real_db["academy_memberships"].find_one(
        {"academy_id": ACADEMY, "user_id": "u-staff"}
    )
    assert set(membership["roles"]) == {"coach", role}
    audits = [
        row
        async for row in real_db["audit_logs"].find({"academy_id": ACADEMY, "entity_id": "u-staff"})
    ]
    assert len(audits) == 1
    audit = audits[0]
    assert audit["action"] == "user.role_added"
    assert audit["actor_id"] == "u-owner"
    assert audit["reason"] == "New hire"
    assert audit["before"]["roles"] == ["coach"]
    assert set(audit["after"]["roles"]) == {"coach", role}


@pytest.mark.asyncio
async def test_revoking_a_staff_tier_writes_a_removal_audit_row(real_db: Any) -> None:
    await _seed(real_db, "u-owner", ["owner"])
    await _seed(real_db, "u-desk", ["front_desk", "coach"])

    await _repo(real_db).remove_role(
        "u-desk", "front_desk", academy_id=ACADEMY, actor_id="u-owner", reason="Moved on"
    )

    membership = await real_db["academy_memberships"].find_one(
        {"academy_id": ACADEMY, "user_id": "u-desk"}
    )
    assert membership["roles"] == ["coach"]
    audit = await real_db["audit_logs"].find_one({"entity_id": "u-desk"})
    assert audit["action"] == "user.role_removed"
    assert audit["actor_id"] == "u-owner"


@pytest.mark.asyncio
async def test_removing_the_last_owner_role_is_refused(real_db: Any) -> None:
    await _seed(real_db, "u-owner", ["owner", "admin"])

    with pytest.raises(CannotRemoveLastOwner):
        await _repo(real_db).remove_role(
            "u-owner", "owner", academy_id=ACADEMY, actor_id="u-x", reason="oops"
        )

    membership = await real_db["academy_memberships"].find_one({"user_id": "u-owner"})
    assert "owner" in membership["roles"]
    stored = await real_db["users"].find_one({"user_id": "u-owner"})
    assert "owner" in stored["roles"]
    assert await real_db["audit_logs"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_an_owner_can_be_removed_while_another_live_owner_remains(real_db: Any) -> None:
    await _seed(real_db, "u-owner", ["owner", "admin"])
    await _seed(real_db, "u-co-owner", ["owner"])

    detail = await _repo(real_db).remove_role(
        "u-owner", "owner", academy_id=ACADEMY, actor_id="u-co-owner", reason="Stepped back"
    )

    assert detail is not None and list(detail.roles) == ["admin"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["invited", "suspended"])
async def test_an_owner_who_cannot_sign_in_does_not_count(real_db: Any, status: str) -> None:
    await _seed(real_db, "u-owner", ["owner", "admin"])
    await _seed(real_db, "u-pending", ["owner"], membership_status=status)

    with pytest.raises(CannotRemoveLastOwner):
        await _repo(real_db).remove_role(
            "u-owner", "owner", academy_id=ACADEMY, actor_id="u-x", reason="oops"
        )


@pytest.mark.asyncio
async def test_an_owner_of_another_academy_does_not_count(real_db: Any) -> None:
    await _seed(real_db, "u-owner", ["owner", "admin"])
    await _seed(real_db, "u-elsewhere", ["owner"], academy_id=OTHER_ACADEMY)

    with pytest.raises(CannotRemoveLastOwner):
        await _repo(real_db).remove_role(
            "u-owner", "owner", academy_id=ACADEMY, actor_id="u-x", reason="oops"
        )


@pytest.mark.asyncio
async def test_replacing_the_last_owners_roles_is_refused(real_db: Any) -> None:
    await _seed(real_db, "u-owner", ["owner"])

    with pytest.raises(CannotRemoveLastOwner):
        await _repo(real_db).change_role(
            "u-owner", "billing", academy_id=ACADEMY, actor_id="u-x", reason="oops"
        )

    membership = await real_db["academy_memberships"].find_one({"user_id": "u-owner"})
    assert membership["roles"] == ["owner"]


@pytest.mark.asyncio
async def test_disabling_the_last_owner_is_refused(real_db: Any, monkeypatch) -> None:
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: _NoFirebase())
    await _seed(real_db, "u-owner", ["owner"])

    with pytest.raises(CannotRemoveLastOwner):
        await _repo(real_db).update_admin_user(
            "u-owner",
            UpdateAdminUserCommand(status="disabled", actor_id="u-x", reason="oops"),
            academy_id=ACADEMY,
        )

    membership = await real_db["academy_memberships"].find_one({"user_id": "u-owner"})
    assert membership["status"] == "active"
