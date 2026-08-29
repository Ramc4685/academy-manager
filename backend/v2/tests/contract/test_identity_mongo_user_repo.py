"""Identity repository auth-bootstrap behavior."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from backend.v2.contexts.identity.domain.errors import RoleRevocationFailed
from backend.v2.contexts.identity.infrastructure import mongo_user_repo as user_repo_module
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository


@pytest.mark.asyncio
async def test_user_repo_reads_legacy_user_without_tenant_scope(db) -> None:
    await db["users"].insert_one(
        {
            "email": "Coach@Badminton.App",
            "name": "Coach Demo",
            "role": "coach",
            "status": "active",
        }
    )

    repo = MongoUserRepository(db, default_academy_id="local-academy")

    user = await repo.get_by_email("coach@badminton.app")

    assert user is not None
    assert user.email.lower() == "coach@badminton.app"
    assert user.display_name == "Coach Demo"
    assert user.roles == ("coach",)
    assert user.is_active is True
    assert user.academy_id == "local-academy"


@pytest.mark.asyncio
async def test_user_repo_maps_v2_user_shape(db) -> None:
    await db["users"].insert_one(
        {
            "user_id": "u-admin",
            "email": "admin@example.com",
            "display_name": "Admin User",
            "roles": ["admin"],
            "is_active": True,
            "academy_id": "academy-a",
        }
    )

    repo = MongoUserRepository(db, default_academy_id="local-academy")

    user = await repo.get_by_email("admin@example.com")

    assert user is not None
    assert user.user_id == "u-admin"
    assert user.roles == ("admin",)
    assert user.academy_id == "academy-a"


@pytest.mark.asyncio
async def test_admin_user_listing_is_scoped_to_academy(db) -> None:
    await db["users"].insert_many(
        [
            {
                "user_id": "u-a",
                "email": "admin-a@example.com",
                "display_name": "Admin A",
                "roles": ["admin"],
                "status": "active",
                "academy_id": "academy-a",
            },
            {
                "user_id": "u-b",
                "email": "admin-b@example.com",
                "display_name": "Admin B",
                "roles": ["admin"],
                "status": "active",
                "academy_id": "academy-b",
            },
        ]
    )

    repo = MongoUserRepository(db, default_academy_id="academy-a")

    users = await repo.list_users(role="admin", academy_id="academy-a")

    assert [u.user_id for u in users] == ["u-a"]


@pytest.mark.asyncio
async def test_user_repo_bootstraps_new_public_parent(db) -> None:
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    user = await repo.ensure_parent_user(
        email="parent@example.com",
        display_name="Parent One",
        firebase_uid="firebase-parent-1",
        academy_id="academy-a",
    )

    assert user.user_id == "firebase-parent-1"
    assert user.roles == ("parent",)
    assert user.academy_id == "academy-a"

    stored = await db["users"].find_one({"email": "parent@example.com"})
    assert stored["auth_provider"] == "firebase"
    assert stored["firebase_uid"] == "firebase-parent-1"


@pytest.mark.asyncio
async def test_user_repo_adds_parent_role_without_dropping_existing_roles(db) -> None:
    await db["users"].insert_one(
        {
            "user_id": "coach-1",
            "email": "coach-parent@example.com",
            "display_name": "Coach Parent",
            "roles": ["coach"],
            "role": "coach",
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    user = await repo.ensure_parent_user(
        email="coach-parent@example.com",
        display_name="Coach Parent",
        firebase_uid="firebase-coach-parent",
        academy_id="academy-a",
    )

    assert user.roles == ("coach", "parent")
    stored = await db["users"].find_one({"email": "coach-parent@example.com"})
    assert stored["role"] == "coach"
    # Original tenant preserved on existing users; the new academy_id
    # argument is only honored on first insert (fixes #81).
    assert stored["academy_id"] == "academy-a"


@pytest.mark.asyncio
async def test_billing_setup_login_signal_is_global_membership_aware_and_firebase_linked(
    db,
) -> None:
    await db["users"].insert_many(
        [
            {
                "user_id": "linked",
                "firebase_uid": "firebase-linked",
                "email": "linked@example.com",
                "academy_id": "academy-a",
            },
            {
                "user_id": "mongo-only",
                "email": "mongo@example.com",
                "academy_id": "academy-b",
            },
            {
                "user_id": "pending",
                "firebase_uid": "firebase-pending",
                "email": "pending@example.com",
                "academy_id": "academy-b",
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "academy-b",
                "user_id": "firebase-linked",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "academy-b",
                "user_id": "firebase-pending",
                "roles": ["parent"],
                "status": "active",
                "login_invite_pending": True,
            },
            {
                "academy_id": "academy-a",
                "user_id": "firebase-pending",
                "roles": ["parent"],
                "status": "active",
            },
        ]
    )
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    found = await repo.list_existing_user_ids(
        ["linked", "mongo-only", "pending"], academy_id="academy-b"
    )

    assert found == {"linked"}
    assert await repo.list_existing_user_ids(["pending"], academy_id="academy-a") == {"pending"}
    assert await repo.get_billing_setup_parent("linked", academy_id="academy-b") is not None
    assert await repo.get_billing_setup_parent("linked", academy_id="academy-a") is None
    assert await repo.get_login_invite_user("linked", academy_id="academy-b") is not None


@pytest.mark.asyncio
async def test_login_invite_finds_legacy_parent_with_membership_keyed_by_user_id(db) -> None:
    """Regression: a roster parent imported before Firebase provisioning has
    no `firebase_uid`/`auth_uid` at all, and its `academy_memberships` row is
    keyed by the plain `user_id`. `get_login_invite_user` previously required
    `firebase_uid` and matched membership only on that field, so this legacy
    shape 404'd even though the account can otherwise log in (see
    `load_auth_claims.py`, which resolves membership the same way `user_id`
    is resolved here)."""
    from datetime import UTC, datetime

    await db["users"].insert_one(
        {
            "user_id": "legacy-parent-1",
            "email": "legacy@example.com",
            "display_name": "Legacy Parent",
            "role": "parent",
            "roles": ["parent"],
            "academy_id": "academy-b",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "academy_id": "academy-b",
            "user_id": "legacy-parent-1",
            "roles": ["parent"],
            "status": "active",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    found = await repo.get_login_invite_user("legacy-parent-1", academy_id="academy-b")
    assert found is not None
    assert found.email == "legacy@example.com"

    sent_at = datetime.now(UTC)
    await repo.record_login_invite("legacy-parent-1", academy_id="academy-b", sent_at=sent_at)
    membership = await db["academy_memberships"].find_one(
        {"academy_id": "academy-b", "user_id": "legacy-parent-1"}
    )
    assert membership is not None
    assert membership["login_invite_sent_at"] is not None


@pytest.mark.asyncio
async def test_billing_setup_provisioning_remains_invite_pending_for_safe_resend(
    db, monkeypatch
) -> None:
    class _Firebase:
        async def ensure_user(self, **kwargs):
            return kwargs["uid"], False

    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: _Firebase())
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    uid = await repo.ensure_parent_login(
        parent_id="parent-1",
        email="parent@example.com",
        display_name="Parent One",
        academy_id="academy-b",
        actor_id="admin-1",
    )
    repeated_uid = await repo.ensure_parent_login(
        parent_id="parent-1",
        email="parent@example.com",
        display_name="Parent One",
        academy_id="academy-b",
        actor_id="admin-1",
    )

    assert uid == repeated_uid == "parent-1"
    user = await db["users"].find_one({"user_id": "parent-1"})
    assert user is not None and "login_invite_pending" not in user
    membership = await db["academy_memberships"].find_one(
        {"academy_id": "academy-b", "user_id": "parent-1"}
    )
    assert membership is not None and membership["login_invite_pending"] is True
    assert await repo.list_existing_user_ids(["parent-1"], academy_id="academy-b") == set()

    sent_at = membership["updated_at"]
    await repo.record_login_invite("parent-1", academy_id="academy-b", sent_at=sent_at)
    delivered = await db["academy_memberships"].find_one(
        {"academy_id": "academy-b", "user_id": "parent-1"}
    )
    assert delivered is not None and "login_invite_pending" not in delivered
    assert await repo.list_existing_user_ids(["parent-1"], academy_id="academy-b") == {"parent-1"}


@pytest.mark.asyncio
async def test_recorded_login_invite_is_visible_on_admin_detail(db) -> None:
    """Regression: `record_login_invite` writes `login_invite_sent_at` to the
    `academy_memberships` row, but the admin detail view used to read it back
    off the `users` doc -- which is never written -- so the field was always
    None. The admin user page therefore kept showing "No invite sent yet"
    after a successful send, admins re-sent, and every re-send mints a fresh
    Firebase oobCode that invalidates the link already emailed to the parent.

    Uses the production shape where the membership is keyed by `firebase_uid`
    rather than the roster `user_id`.
    """
    from datetime import UTC, datetime

    await db["users"].insert_one(
        {
            "user_id": "roster-parent-1",
            "auth_uid": "fb-uid-1",
            "firebase_uid": "fb-uid-1",
            "email": "invited@example.com",
            "display_name": "Invited Parent",
            "role": "parent",
            "roles": ["parent"],
            "academy_id": "academy-b",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "academy_id": "academy-b",
            "user_id": "fb-uid-1",
            "roles": ["parent"],
            "status": "active",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    before = await repo.get_admin_user("roster-parent-1", academy_id="academy-b")
    assert before is not None and before.login_invite_sent_at is None

    await repo.record_login_invite(
        "roster-parent-1", academy_id="academy-b", sent_at=datetime.now(UTC)
    )

    detail = await repo.get_admin_user("roster-parent-1", academy_id="academy-b")
    assert detail is not None
    assert detail.login_invite_sent_at is not None

    invite_target = await repo.get_login_invite_user("roster-parent-1", academy_id="academy-b")
    assert invite_target is not None
    assert invite_target.login_invite_sent_at is not None

    # The users doc stays untouched: the membership row is the only writer, so
    # re-reading the field from `users` would silently regress it to None.
    user_doc = await db["users"].find_one({"user_id": "roster-parent-1"})
    assert user_doc is not None and "login_invite_sent_at" not in user_doc


@pytest.mark.asyncio
async def test_admin_detail_login_invite_is_scoped_to_the_requesting_academy(db) -> None:
    """An invite sent in one tenant must not read as sent in another: the
    timestamp lives on the per-academy membership row, not on the shared
    global `users` doc."""
    from datetime import UTC, datetime

    await db["users"].insert_one(
        {
            "user_id": "shared-parent",
            "auth_uid": "shared-parent",
            "firebase_uid": "shared-parent",
            "email": "shared@example.com",
            "display_name": "Shared Parent",
            "role": "parent",
            "roles": ["parent"],
            "academy_id": "academy-b",
        }
    )
    for academy_id in ("academy-b", "academy-c"):
        await db["academy_memberships"].insert_one(
            {
                "academy_id": academy_id,
                "user_id": "shared-parent",
                "roles": ["parent"],
                "status": "active",
            }
        )
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    await repo.record_login_invite(
        "shared-parent", academy_id="academy-b", sent_at=datetime.now(UTC)
    )

    invited = await repo.get_login_invite_user("shared-parent", academy_id="academy-b")
    assert invited is not None and invited.login_invite_sent_at is not None

    other = await repo.get_login_invite_user("shared-parent", academy_id="academy-c")
    assert other is not None and other.login_invite_sent_at is None


class _RecordingFirebase:
    def __init__(self) -> None:
        self.email_updates: list[tuple[str, str]] = []

    async def update_user_email(self, uid: str, email: str) -> None:
        self.email_updates.append((uid, email))


async def _seed_editable_parent(db) -> None:
    await db["users"].insert_one(
        {
            "user_id": "roster-parent-9",
            "auth_uid": "fb-uid-9",
            "firebase_uid": "fb-uid-9",
            "email": "Parent@Example.com",
            "normalized_email": "parent@example.com",
            "display_name": "Parent Nine",
            "role": "parent",
            "roles": ["parent"],
            "status": "active",
            "academy_id": "academy-b",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "academy_id": "academy-b",
            "user_id": "fb-uid-9",
            "roles": ["parent"],
            "status": "active",
        }
    )


@pytest.mark.asyncio
async def test_resubmitting_the_same_email_does_not_touch_firebase(db, monkeypatch) -> None:
    """#436: `update_user_email` clears `email_verified`, which blocks password
    login. A no-op edit (or a casing-only one) must not cost the parent their
    verified state, since nothing about the address actually changed."""
    from backend.v2.contexts.identity.application.use_cases.admin_directory import (
        UpdateAdminUserCommand,
    )

    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    await _seed_editable_parent(db)
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    updated = await repo.update_admin_user(
        "roster-parent-9",
        UpdateAdminUserCommand(
            email="PARENT@example.com",
            display_name="Parent Renamed",
            actor_id="admin-1",
            reason="name fix",
        ),
        academy_id="academy-b",
    )

    assert updated is not None and updated.display_name == "Parent Renamed"
    assert firebase.email_updates == []


@pytest.mark.asyncio
async def test_changing_the_email_updates_firebase(db, monkeypatch) -> None:
    from backend.v2.contexts.identity.application.use_cases.admin_directory import (
        UpdateAdminUserCommand,
    )

    firebase = _RecordingFirebase()
    monkeypatch.setattr(user_repo_module, "get_firebase_admin_adapter", lambda: firebase)
    await _seed_editable_parent(db)
    repo = MongoUserRepository(db, default_academy_id="academy-b")

    updated = await repo.update_admin_user(
        "roster-parent-9",
        UpdateAdminUserCommand(
            email="corrected@example.com",
            actor_id="admin-1",
            reason="typo fix",
        ),
        academy_id="academy-b",
    )

    assert updated is not None and updated.email == "corrected@example.com"
    assert firebase.email_updates == [("fb-uid-9", "corrected@example.com")]


# ---------------------------------------------------------------------------
# Role replacement must reach the SaaS source of truth
# ---------------------------------------------------------------------------


class _StubVerifier:
    def __init__(self, email: str) -> None:
        self._email = email

    async def verify(self, id_token: str) -> dict[str, object]:
        return {"email": self._email, "email_verified": True}


class _NoPlatformRoles:
    async def list_active_for_user(self, user_id: str) -> list:
        return []


async def _claims_for(db, repo: MongoUserRepository, email: str, *, academy_id: str):
    """Build the claims the auth middleware would hand a request."""
    from backend.v2.contexts.identity.application.use_cases.load_auth_claims import (
        LoadAuthClaims,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
        MongoMembershipRepository,
    )

    use_case = LoadAuthClaims(
        _StubVerifier(email),
        repo,
        MongoMembershipRepository(db),
        _NoPlatformRoles(),
    )
    return await use_case.execute("id-token", resolved_academy_id=academy_id)


async def _seed_admin_with_membership(db, *, user_id: str, membership_user_id: str) -> None:
    await db["users"].insert_one(
        {
            "user_id": user_id,
            "auth_uid": membership_user_id,
            "email": "terminated-staff@example.com",
            "display_name": "Terminated Staff",
            "role": "admin",
            "roles": ["admin"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-staff",
            "academy_id": "academy-a",
            "user_id": membership_user_id,
            "roles": ["admin"],
            "status": "active",
        }
    )


@pytest.mark.asyncio
async def test_role_change_revokes_the_old_role_in_saas_claims(db) -> None:
    """Demoting admin -> parent must stop the claims granting `admin`.

    SaaS claims are built from `academy_memberships` (LoadAuthClaims), not
    from the legacy users doc, so a replacement that only rewrites `users`
    leaves the demoted staff member with full admin access.
    """
    await _seed_admin_with_membership(db, user_id="u-staff", membership_user_id="u-staff")
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    summary = await repo.change_role(
        "u-staff",
        "parent",
        academy_id="academy-a",
        actor_id="admin-1",
        reason="offboarded",
    )
    assert summary is not None

    claims = await _claims_for(db, repo, "terminated-staff@example.com", academy_id="academy-a")
    assert claims.roles == ("parent",)


@pytest.mark.asyncio
async def test_role_change_mirrors_membership_keyed_by_an_identity_alias(db) -> None:
    """The membership row may be keyed by `auth_uid`/`firebase_uid` rather
    than `users.user_id` (see `identity_aliases`); the revocation has to
    match the same alias set the login path does."""
    await _seed_admin_with_membership(db, user_id="roster-staff", membership_user_id="fb-staff")
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    await repo.change_role(
        "roster-staff",
        "parent",
        academy_id="academy-a",
        actor_id="admin-1",
        reason="offboarded",
    )

    membership = await db["academy_memberships"].find_one({"membership_id": "m-staff"})
    assert membership["roles"] == ["parent"]


@pytest.mark.asyncio
async def test_role_change_mirrors_membership_keyed_by_the_document_id(db) -> None:
    """A legacy doc with no `user_id`/`auth_uid` is keyed by `str(_id)`.

    That is what `_to_domain` resolves as the user id and what the claims
    path aliases on, but it is not one of the three id *fields*
    `aliases_from_doc` reads — so revoking with that narrower set walks past
    the very row `LoadAuthClaims` is granting from.
    """
    result = await db["users"].insert_one(
        {
            "firebase_uid": "fb-legacy",
            "email": "legacy-staff@example.com",
            "display_name": "Legacy Staff",
            "role": "admin",
            "roles": ["admin"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-legacy",
            "academy_id": "academy-a",
            "user_id": str(result.inserted_id),
            "roles": ["admin"],
            "status": "active",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    await repo.change_role(
        str(result.inserted_id),
        "parent",
        academy_id="academy-a",
        actor_id="admin-1",
        reason="offboarded",
    )

    claims = await _claims_for(db, repo, "legacy-staff@example.com", academy_id="academy-a")
    assert claims.roles == ("parent",)


@pytest.mark.asyncio
async def test_role_change_mirrors_this_academy_only(db) -> None:
    """The mirror lands in the academy the change applies to, and only there.

    Both halves are asserted on purpose: the tenant-isolation half alone
    passes just as well with no mirror at all, so it proves nothing about
    scope on its own.
    """
    await _seed_admin_with_membership(db, user_id="u-staff", membership_user_id="u-staff")
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-other",
            "academy_id": "academy-b",
            "user_id": "u-staff",
            "roles": ["admin"],
            "status": "active",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    await repo.change_role(
        "u-staff",
        "parent",
        academy_id="academy-a",
        actor_id="admin-1",
        reason="offboarded",
    )

    here = await db["academy_memberships"].find_one({"membership_id": "m-staff"})
    assert here["roles"] == ["parent"]
    other = await db["academy_memberships"].find_one({"membership_id": "m-other"})
    assert other["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_role_change_does_not_rewrite_a_colliding_accounts_membership(db) -> None:
    """An alias of one account can be another account's primary `user_id`.

    Roster ids and Firebase uids are minted by different paths, so the
    demoted admin's `auth_uid` can equal a second account's `users.user_id`.
    Matching memberships by alias with an uncapped `update_many` flattens
    that second account's roles to the demoted role as well.
    """
    await _seed_admin_with_membership(db, user_id="u-staff", membership_user_id="shared-uid")
    await db["users"].insert_one(
        {
            "user_id": "shared-uid",
            "email": "other-admin@example.com",
            "display_name": "Other Admin",
            "role": "admin",
            "roles": ["admin"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    # `m-staff` is keyed by the demoted account's `auth_uid`; this row is the
    # other account's own membership, keyed by its primary `user_id` — the
    # same string.
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-other-admin",
            "academy_id": "academy-a",
            "user_id": "shared-uid",
            "roles": ["admin"],
            "status": "active",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    # Both alias-matched rows are keyed by the shared id, which is the OTHER
    # account's primary `user_id`, so neither can be claimed. Previously the
    # demotion skipped both and reported success — leaving `u-staff`'s own row
    # at `admin`, which `LoadAuthClaims` still resolves through the same alias.
    # It now fails closed instead of reporting a demotion that never happened.
    with pytest.raises(RoleRevocationFailed):
        await repo.change_role(
            "u-staff",
            "parent",
            academy_id="academy-a",
            actor_id="admin-1",
            reason="offboarded",
        )

    bystander = await db["academy_memberships"].find_one({"membership_id": "m-other-admin"})
    assert bystander["roles"] == ["admin"]
    claims = await _claims_for(db, repo, "other-admin@example.com", academy_id="academy-a")
    assert claims.roles == ("admin",)


@pytest.mark.asyncio
async def test_role_change_reports_when_no_membership_row_matched(db, caplog) -> None:
    """A narrowing that reaches no membership row must be detectable.

    A row keyed outside every identity alias cannot be found from here — and
    cannot grant anything either, since `LoadAuthClaims` resolves through the
    same alias set. What is unacceptable is doing it silently: the operator
    is told the demotion happened, so the miss has to leave a trace.
    """
    await _seed_admin_with_membership(db, user_id="u-staff", membership_user_id="u-staff")
    await db["academy_memberships"].delete_one({"membership_id": "m-staff"})
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-mis-keyed",
            "academy_id": "academy-a",
            "user_id": "roster-legacy-9",  # on neither the users doc nor the claims path
            "roles": ["admin"],
            "status": "active",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    with caplog.at_level(logging.WARNING, logger=user_repo_module.__name__):
        await repo.change_role(
            "u-staff",
            "parent",
            academy_id="academy-a",
            actor_id="admin-1",
            reason="offboarded",
        )

    assert [record.message for record in caplog.records] == [
        "role change matched no membership row to revoke"
    ]


class _LostMembershipWriteCollection:
    """Reports a membership write that matched nothing, without applying it."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def update_many(self, *args, **kwargs):
        return SimpleNamespace(matched_count=0, modified_count=0)


class _LostMembershipWriteDb:
    def __init__(self, inner) -> None:
        self._inner = inner

    def __getitem__(self, name: str):
        collection = self._inner[name]
        if name == "academy_memberships":
            return _LostMembershipWriteCollection(collection)
        return collection


@pytest.mark.asyncio
async def test_role_change_aborts_when_the_revocation_write_is_lost(db) -> None:
    """A revocation that does not land fails the whole operation.

    The membership write is checked (`matched_count`) and runs *before* the
    directory write, so a lost revocation cannot leave the account listed as
    a parent, unaudited, and still holding live admin claims.
    """
    await _seed_admin_with_membership(db, user_id="u-staff", membership_user_id="u-staff")
    repo = MongoUserRepository(_LostMembershipWriteDb(db), default_academy_id="academy-a")

    with pytest.raises(RoleRevocationFailed):
        await repo.change_role(
            "u-staff",
            "parent",
            academy_id="academy-a",
            actor_id="admin-1",
            reason="offboarded",
        )

    directory = await db["users"].find_one({"user_id": "u-staff"})
    assert directory["roles"] == ["admin"]
    assert await db["audit_logs"].count_documents({}) == 0
    claims = await _claims_for(db, repo, "terminated-staff@example.com", academy_id="academy-a")
    assert claims.roles == ("admin",)


@pytest.mark.asyncio
async def test_role_change_fails_closed_when_the_only_row_is_alias_owned(db) -> None:
    """A demotion that cannot claim an alias-visible row must not report success.

    The staff account's membership row is keyed by its `auth_uid`, and that
    value is another account's primary `users.user_id`. The row is therefore
    skipped as foreign — rewriting it could flatten the other account's roles.

    But `LoadAuthClaims` resolves through the same alias set, so it still reads
    that row and keeps serving `admin`. Reporting the demotion as done would
    leave live admin claims behind an audit trail saying "parent", so the whole
    operation fails instead and asks a human to untangle the collision.
    """
    await _seed_admin_with_membership(db, user_id="u-staff", membership_user_id="shared-id")
    # Another account legitimately owns "shared-id" as its primary user_id.
    await db["users"].insert_one(
        {
            "user_id": "shared-id",
            "email": "other-account@example.com",
            "display_name": "Other Account",
            "role": "coach",
            "roles": ["coach"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    with pytest.raises(RoleRevocationFailed):
        await repo.change_role(
            "u-staff",
            "parent",
            academy_id="academy-a",
            actor_id="admin-1",
            reason="offboarded",
        )

    # Nothing was reported as done, and nothing was half-written.
    directory = await db["users"].find_one({"user_id": "u-staff"})
    assert directory["roles"] == ["admin"]
    assert await db["audit_logs"].count_documents({}) == 0
    # The other account's row is untouched — the skip did its job.
    row = await db["academy_memberships"].find_one({"membership_id": "m-staff"})
    assert row["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_promotion_writes_the_directory_before_granting_the_membership(db) -> None:
    """A widening must never leave claims wider than the directory shows.

    Demotions revoke the membership first so a partial failure can only ever
    narrow access. A promotion has to run the other way round: granting the
    membership first and then failing the directory write would hand out live
    admin claims that the admin UI still renders as `parent` — fail-open, and
    invisible to whoever reads the directory.
    """
    await db["users"].insert_one(
        {
            "user_id": "u-parent",
            "auth_uid": "u-parent",
            "email": "promoted@example.com",
            "display_name": "Promoted Parent",
            "role": "parent",
            "roles": ["parent"],
            "status": "active",
            "is_active": True,
            "academy_id": "academy-a",
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "m-parent",
            "academy_id": "academy-a",
            "user_id": "u-parent",
            "roles": ["parent"],
            "status": "active",
        }
    )
    repo = MongoUserRepository(db, default_academy_id="academy-a")

    order: list[str] = []
    real_replace = repo._replace_membership_roles
    real_update = repo.collection.find_one_and_update

    async def _tracked_replace(*args, **kwargs):
        order.append("membership")
        return await real_replace(*args, **kwargs)

    async def _tracked_update(*args, **kwargs):
        order.append("directory")
        return await real_update(*args, **kwargs)

    repo._replace_membership_roles = _tracked_replace  # type: ignore[method-assign]
    repo.collection.find_one_and_update = _tracked_update  # type: ignore[method-assign]
    try:
        await repo.change_role(
            "u-parent",
            "admin",
            academy_id="academy-a",
            actor_id="admin-1",
            reason="promoted to staff",
        )
    finally:
        repo.collection.find_one_and_update = real_update  # type: ignore[method-assign]

    assert order == ["directory", "membership"], (
        "a promotion must write the directory before granting the membership, "
        "so a partial failure cannot leave claims wider than the directory"
    )
    claims = await _claims_for(db, repo, "promoted@example.com", academy_id="academy-a")
    assert claims.roles == ("admin",)
