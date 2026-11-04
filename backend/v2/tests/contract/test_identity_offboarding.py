"""Staff/parent offboarding cascades (#785).

Three orphan classes this file pins:

1. "Disable" was a no-op for auth. ``_to_domain`` never mapped the stored
   status onto ``User.global_status``, which defaults to ``"active"``, and
   ``LoadAuthClaims._user_is_active`` trusts ``global_status`` *first* — so a
   disabled parent kept signing in and kept being billed.
2. Disabling never touched the academy membership or Firebase, so even a
   correct ``global_status`` left two other live doors open.
3. Removing the ``coach`` role rewrote the ``users.roles`` array and nothing
   else, stranding future occurrences on an ex-coach.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.application.use_cases.load_auth_claims import (
    _user_is_active,
)
from backend.v2.contexts.identity.domain.errors import (
    CoachHasFutureSessions,
    ParentHasLiveChildren,
)
from backend.v2.contexts.identity.infrastructure import mongo_user_repo as user_repo_module
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

ACADEMY = "academy-a"


async def _seed_user(db, **overrides) -> None:
    doc = {
        "user_id": "u-parent",
        "email": "parent@example.com",
        "display_name": "Parent One",
        "roles": ["parent"],
        "status": "active",
        "academy_id": ACADEMY,
    }
    doc.update(overrides)
    await db["users"].insert_one(doc)


async def _seed_membership(db, *, user_id: str, roles: list[str], status: str = "active") -> None:
    await db["academy_memberships"].insert_one(
        {
            "membership_id": f"m-{user_id}",
            "academy_id": ACADEMY,
            "user_id": user_id,
            "roles": roles,
            "status": status,
            "created_at": datetime.now(UTC),
        }
    )


class _RecordingFirebase:
    def __init__(self) -> None:
        self.disabled: list[tuple[str, bool]] = []

    async def set_user_disabled(self, uid: str, disabled: bool) -> None:
        self.disabled.append((uid, disabled))


# ---------------------------------------------------------------------------
# 1. status -> global_status mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_status", ["disabled", "inactive"])
async def test_disabled_directory_status_reaches_global_status(db, stored_status: str) -> None:
    await _seed_user(db, status=stored_status, is_active=False)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    user = await repo.get_by_email("parent@example.com")

    assert user is not None
    assert user.global_status == "disabled"
    assert user.is_active is False
    # The claims path reads `global_status` first; if it is not mapped the
    # legacy `is_active` fallback is never consulted and sign-in succeeds.
    assert _user_is_active(user) is False


@pytest.mark.asyncio
async def test_user_without_a_status_field_stays_active(db) -> None:
    """Backfill safety: a doc predating the field must not lock its owner out."""
    await db["users"].insert_one(
        {
            "user_id": "u-legacy",
            "email": "legacy@example.com",
            "display_name": "Legacy",
            "roles": ["parent"],
            "academy_id": ACADEMY,
        }
    )
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    user = await repo.get_by_email("legacy@example.com")

    assert user is not None
    assert user.global_status == "active"
    assert _user_is_active(user) is True


@pytest.mark.asyncio
async def test_explicit_global_status_wins_over_legacy_status(db) -> None:
    await _seed_user(db, status="active", global_status="deleted")
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    user = await repo.get_by_email("parent@example.com")

    assert user is not None
    assert user.global_status == "deleted"
    assert _user_is_active(user) is False


# ---------------------------------------------------------------------------
# 2. the disable write cascades to membership + Firebase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabling_suspends_the_membership_and_disables_firebase(db, monkeypatch) -> None:
    await _seed_user(db, firebase_uid="fb-parent")
    await _seed_membership(db, user_id="u-parent", roles=["parent"])
    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.update_admin_user(
        "u-parent",
        UpdateAdminUserCommand(status="disabled", actor_id="admin-1", reason="left the academy"),
        academy_id=ACADEMY,
    )

    assert detail is not None and detail.status == "disabled"
    stored = await db["users"].find_one({"user_id": "u-parent"})
    assert stored["global_status"] == "disabled"
    assert stored["is_active"] is False
    membership = await db["academy_memberships"].find_one({"user_id": "u-parent"})
    assert membership["status"] == "suspended"
    assert firebase.disabled == [("fb-parent", True)]


@pytest.mark.asyncio
async def test_reenabling_restores_the_membership_and_firebase_account(db, monkeypatch) -> None:
    await _seed_user(db, firebase_uid="fb-parent", status="disabled", is_active=False)
    await _seed_membership(db, user_id="u-parent", roles=["parent"], status="suspended")
    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    await repo.update_admin_user(
        "u-parent",
        UpdateAdminUserCommand(status="active", actor_id="admin-1", reason="returned"),
        academy_id=ACADEMY,
    )

    stored = await db["users"].find_one({"user_id": "u-parent"})
    assert stored["global_status"] == "active"
    membership = await db["academy_memberships"].find_one({"user_id": "u-parent"})
    assert membership["status"] == "active"
    assert firebase.disabled == [("fb-parent", False)]


@pytest.mark.asyncio
async def test_a_firebase_outage_does_not_block_the_local_disable(db, monkeypatch) -> None:
    """Locking the account out of *our* database is the part that must land."""

    class _Broken:
        async def set_user_disabled(self, uid: str, disabled: bool) -> None:
            raise RuntimeError("firebase down")

    await _seed_user(db, firebase_uid="fb-parent")
    await _seed_membership(db, user_id="u-parent", roles=["parent"])
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: _Broken())
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.update_admin_user(
        "u-parent",
        UpdateAdminUserCommand(status="disabled", actor_id="admin-1", reason="left"),
        academy_id=ACADEMY,
    )

    assert detail is not None and detail.status == "disabled"
    stored = await db["users"].find_one({"user_id": "u-parent"})
    assert stored["global_status"] == "disabled"
    membership = await db["academy_memberships"].find_one({"user_id": "u-parent"})
    assert membership["status"] == "suspended"


# ---------------------------------------------------------------------------
# 3. coach role removal cannot strand future occurrences
# ---------------------------------------------------------------------------


async def _seed_occurrence(db, **overrides) -> None:
    doc = {
        "occurrence_id": "occ-1",
        "academy_id": ACADEMY,
        "session_id": "sess-1",
        "start_at": datetime.now(UTC) + timedelta(days=7),
        "scheduled_coach_id": "u-coach",
        "status": "scheduled",
    }
    doc.update(overrides)
    await db["session_occurrences"].insert_one(doc)


@pytest.mark.asyncio
async def test_removing_coach_role_is_refused_while_future_occurrences_remain(db) -> None:
    await _seed_user(db, user_id="u-coach", email="coach@example.com", roles=["coach", "parent"])
    await _seed_membership(db, user_id="u-coach", roles=["coach", "parent"])
    await _seed_occurrence(db)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    with pytest.raises(CoachHasFutureSessions):
        await repo.remove_role(
            "u-coach", "coach", academy_id=ACADEMY, actor_id="admin-1", reason="left"
        )

    stored = await db["users"].find_one({"user_id": "u-coach"})
    assert "coach" in stored["roles"]


@pytest.mark.asyncio
async def test_removing_coach_role_is_refused_for_a_future_assistant_assignment(db) -> None:
    await _seed_user(
        db, user_id="u-coach", email="coach@example.com", roles=["assistant_coach", "parent"]
    )
    await _seed_membership(db, user_id="u-coach", roles=["assistant_coach", "parent"])
    await _seed_occurrence(db, scheduled_coach_id="u-someone-else", assistant_coach_ids=["u-coach"])
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    with pytest.raises(CoachHasFutureSessions):
        await repo.remove_role(
            "u-coach", "assistant_coach", academy_id=ACADEMY, actor_id="admin-1", reason="left"
        )


@pytest.mark.asyncio
async def test_removing_coach_role_succeeds_once_only_past_occurrences_remain(db) -> None:
    await _seed_user(db, user_id="u-coach", email="coach@example.com", roles=["coach", "parent"])
    await _seed_membership(db, user_id="u-coach", roles=["coach", "parent"])
    await _seed_occurrence(db, start_at=datetime.now(UTC) - timedelta(days=7), status="completed")
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.remove_role(
        "u-coach", "coach", academy_id=ACADEMY, actor_id="admin-1", reason="left"
    )

    assert detail is not None
    stored = await db["users"].find_one({"user_id": "u-coach"})
    assert "coach" not in stored["roles"]


@pytest.mark.asyncio
async def test_a_cancelled_future_occurrence_does_not_block_removal(db) -> None:
    await _seed_user(db, user_id="u-coach", email="coach@example.com", roles=["coach", "parent"])
    await _seed_membership(db, user_id="u-coach", roles=["coach", "parent"])
    await _seed_occurrence(db, status="cancelled")
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.remove_role(
        "u-coach", "coach", academy_id=ACADEMY, actor_id="admin-1", reason="left"
    )

    assert detail is not None


@pytest.mark.asyncio
async def test_future_occurrences_in_another_academy_do_not_block_removal(db) -> None:
    await _seed_user(db, user_id="u-coach", email="coach@example.com", roles=["coach", "parent"])
    await _seed_membership(db, user_id="u-coach", roles=["coach", "parent"])
    await _seed_occurrence(db, academy_id="academy-b")
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.remove_role(
        "u-coach", "coach", academy_id=ACADEMY, actor_id="admin-1", reason="left"
    )

    assert detail is not None


@pytest.mark.asyncio
async def test_removing_a_non_coaching_role_ignores_the_session_guard(db) -> None:
    await _seed_user(db, user_id="u-coach", email="coach@example.com", roles=["coach", "parent"])
    await _seed_membership(db, user_id="u-coach", roles=["coach", "parent"])
    await _seed_occurrence(db)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.remove_role(
        "u-coach", "parent", academy_id=ACADEMY, actor_id="admin-1", reason="not a parent"
    )

    assert detail is not None


# ---------------------------------------------------------------------------
# 4. the DISABLE door clears the same dated-work guards as role removal
# ---------------------------------------------------------------------------


async def _seed_student(db, *, student_id: str, parent_id: str) -> None:
    await db["students"].insert_one(
        {
            "student_id": student_id,
            "academy_id": ACADEMY,
            "parent_id": parent_id,
            "first_name": "Kid",
        }
    )


async def _seed_enrollment(db, *, student_id: str, status: str = "active") -> None:
    await db["enrollments"].insert_one(
        {
            "enrollment_id": f"enr-{student_id}-{status}",
            "academy_id": ACADEMY,
            "student_id": student_id,
            "session_id": "sess-1",
            "status": status,
        }
    )


def _disable(status: str = "disabled") -> UpdateAdminUserCommand:
    return UpdateAdminUserCommand(status=status, actor_id="admin-1", reason="left the academy")


@pytest.mark.asyncio
async def test_disabling_a_coach_with_future_occurrences_is_refused(db, monkeypatch) -> None:
    """Disable is wider than role removal, so it cannot be the softer door."""
    await _seed_user(db, user_id="u-coach", email="coach@example.com", roles=["coach"])
    await _seed_membership(db, user_id="u-coach", roles=["coach"])
    await _seed_occurrence(db)
    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    with pytest.raises(CoachHasFutureSessions):
        await repo.update_admin_user("u-coach", _disable(), academy_id=ACADEMY)

    stored = await db["users"].find_one({"user_id": "u-coach"})
    assert stored.get("global_status") != "disabled"
    membership = await db["academy_memberships"].find_one({"user_id": "u-coach"})
    assert membership["status"] == "active"
    assert firebase.disabled == []


@pytest.mark.asyncio
async def test_disabling_a_coach_without_future_work_still_succeeds(db, monkeypatch) -> None:
    await _seed_user(db, user_id="u-coach", email="coach@example.com", roles=["coach"])
    await _seed_membership(db, user_id="u-coach", roles=["coach"])
    await _seed_occurrence(db, start_at=datetime.now(UTC) - timedelta(days=3), status="completed")
    monkeypatch.setattr(
        user_repo_module, "get_firebase_admin_adapter", lambda: _RecordingFirebase()
    )
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.update_admin_user("u-coach", _disable(), academy_id=ACADEMY)

    assert detail is not None and detail.status == "disabled"


@pytest.mark.asyncio
async def test_disabling_a_parent_with_live_enrollments_is_refused(db, monkeypatch) -> None:
    await _seed_user(db)
    await _seed_membership(db, user_id="u-parent", roles=["parent"])
    await _seed_student(db, student_id="s-1", parent_id="u-parent")
    await _seed_enrollment(db, student_id="s-1", status="paused")
    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    with pytest.raises(ParentHasLiveChildren):
        await repo.update_admin_user("u-parent", _disable(), academy_id=ACADEMY)

    membership = await db["academy_memberships"].find_one({"user_id": "u-parent"})
    assert membership["status"] == "active"
    assert firebase.disabled == []


@pytest.mark.asyncio
async def test_disabling_a_parent_whose_children_have_all_withdrawn_succeeds(
    db, monkeypatch
) -> None:
    await _seed_user(db)
    await _seed_membership(db, user_id="u-parent", roles=["parent"])
    await _seed_student(db, student_id="s-1", parent_id="u-parent")
    await _seed_enrollment(db, student_id="s-1", status="withdrawn")
    monkeypatch.setattr(
        user_repo_module, "get_firebase_admin_adapter", lambda: _RecordingFirebase()
    )
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.update_admin_user("u-parent", _disable(), academy_id=ACADEMY)

    assert detail is not None and detail.status == "disabled"


@pytest.mark.asyncio
async def test_reenabling_never_runs_the_offboarding_guards(db, monkeypatch) -> None:
    """The guards protect the *removal* of access, not its restoration."""
    await _seed_user(db, status="disabled", is_active=False)
    await _seed_membership(db, user_id="u-parent", roles=["parent"], status="suspended")
    await _seed_student(db, student_id="s-1", parent_id="u-parent")
    await _seed_enrollment(db, student_id="s-1")
    monkeypatch.setattr(
        user_repo_module, "get_firebase_admin_adapter", lambda: _RecordingFirebase()
    )
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    detail = await repo.update_admin_user(
        "u-parent",
        UpdateAdminUserCommand(status="active", actor_id="admin-1", reason="returned"),
        academy_id=ACADEMY,
    )

    assert detail is not None and detail.status == "active"


# ---------------------------------------------------------------------------
# 5. one tenant's disable must not revoke a shared Firebase identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disable_leaves_firebase_alone_when_another_academy_is_live(db, monkeypatch) -> None:
    await _seed_user(db, firebase_uid="fb-parent")
    await _seed_membership(db, user_id="u-parent", roles=["parent"])
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-other",
            "academy_id": "academy-b",
            "user_id": "fb-parent",
            "roles": ["parent"],
            "status": "active",
        }
    )
    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    await repo.update_admin_user("u-parent", _disable(), academy_id=ACADEMY)

    # This academy is closed...
    membership = await db["academy_memberships"].find_one(
        {"academy_id": ACADEMY, "user_id": "u-parent"}
    )
    assert membership["status"] == "suspended"
    # ...and academy-b's membership and the shared login are untouched.
    other = await db["academy_memberships"].find_one({"academy_id": "academy-b"})
    assert other["status"] == "active"
    assert firebase.disabled == []


@pytest.mark.asyncio
async def test_disable_still_revokes_firebase_when_other_memberships_are_suspended(
    db, monkeypatch
) -> None:
    await _seed_user(db, firebase_uid="fb-parent")
    await _seed_membership(db, user_id="u-parent", roles=["parent"])
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-other",
            "academy_id": "academy-b",
            "user_id": "fb-parent",
            "roles": ["parent"],
            "status": "suspended",
        }
    )
    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    await repo.update_admin_user("u-parent", _disable(), academy_id=ACADEMY)

    assert firebase.disabled == [("fb-parent", True)]


@pytest.mark.asyncio
async def test_enable_does_not_lift_another_academys_lockout(db, monkeypatch) -> None:
    await _seed_user(db, firebase_uid="fb-parent", status="disabled", is_active=False)
    await _seed_membership(db, user_id="u-parent", roles=["parent"], status="suspended")
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-other",
            "academy_id": "academy-b",
            "user_id": "fb-parent",
            "roles": ["parent"],
            "status": "suspended",
        }
    )
    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    repo = MongoUserRepository(db, default_academy_id=ACADEMY)

    await repo.update_admin_user(
        "u-parent",
        UpdateAdminUserCommand(status="active", actor_id="admin-1", reason="returned"),
        academy_id=ACADEMY,
    )

    membership = await db["academy_memberships"].find_one(
        {"academy_id": ACADEMY, "user_id": "u-parent"}
    )
    assert membership["status"] == "active"
    assert firebase.disabled == []
