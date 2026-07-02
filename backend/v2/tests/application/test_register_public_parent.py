from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    RegisterPublicParent,
)
from backend.v2.contexts.identity.domain.errors import InvalidToken, UserInactive
from backend.v2.contexts.identity.domain.models import AcademyMembership, User


class FakeVerifier:
    def __init__(self, claims: dict[str, object]) -> None:
        self.claims = claims

    async def verify(self, id_token: str) -> dict[str, object]:
        assert id_token == "firebase-token"
        return self.claims


class FakeUsers:
    def __init__(self, existing: User | None = None) -> None:
        self.existing = existing
        self.ensure_calls: list[dict[str, str]] = []

    async def get_by_email(self, email: str) -> User | None:
        return (
            self.existing
            if self.existing and self.existing.email.lower() == email.lower()
            else None
        )

    async def get_by_id(self, user_id: str) -> User | None:
        return None

    async def ensure_parent_user(
        self,
        *,
        email: str,
        display_name: str,
        firebase_uid: str,
        academy_id: str,
    ) -> User:
        self.ensure_calls.append(
            {
                "email": email,
                "display_name": display_name,
                "firebase_uid": firebase_uid,
                "academy_id": academy_id,
            }
        )
        return User(
            user_id=firebase_uid,
            email=email,
            display_name=display_name,
            roles=("parent",),
            is_active=True,
            academy_id=academy_id,
        )


class FakeMemberships:
    def __init__(self, existing: AcademyMembership | None = None) -> None:
        self.existing = existing
        self.upserts: list[AcademyMembership] = []

    async def upsert_membership(self, membership: AcademyMembership) -> AcademyMembership:
        self.upserts.append(membership)
        return membership

    async def get_membership(self, academy_id: str, user_id: str):
        if (
            self.existing is not None
            and self.existing.academy_id == academy_id
            and self.existing.user_id == user_id
        ):
            return self.existing
        return None

    async def list_memberships_for_user(self, user_id: str):  # pragma: no cover
        return []

    async def list_active_platform_roles(self, user_id: str):  # pragma: no cover
        return []

    async def upsert_platform_role(self, platform_role):  # pragma: no cover
        return platform_role


class FakeOutbox:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[object] = []

    async def append(self, event, *, session=None) -> None:
        _ = session
        if self.fail:
            raise RuntimeError("outbox unavailable")
        self.events.append(event)

    async def pull_unprocessed(self, limit: int = 100):  # pragma: no cover
        _ = limit
        return []

    async def mark_processed(self, event_id: str) -> None:  # pragma: no cover
        _ = event_id


# ---------------------------------------------------------------------------
# Legacy single-tenant fallback (no academy_id passed; default used)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_public_parent_bootstraps_parent_role_legacy() -> None:
    users = FakeUsers()
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=users,
        default_academy_id="legacy-academy",
        saas_mode=False,
    )

    user = await use_case.execute("firebase-token")

    assert user.roles == ("parent",)
    assert user.user_id == "firebase-parent-1"
    assert users.ensure_calls == [
        {
            "email": "new.parent@example.com",
            "display_name": "New Parent",
            "firebase_uid": "firebase-parent-1",
            "academy_id": "legacy-academy",
        }
    ]


@pytest.mark.asyncio
async def test_register_public_parent_requires_email_and_uid() -> None:
    use_case = RegisterPublicParent(
        verifier=FakeVerifier({"email": "parent@example.com"}),
        users=FakeUsers(),
    )

    with pytest.raises(InvalidToken):
        await use_case.execute("firebase-token")


@pytest.mark.asyncio
async def test_register_public_parent_rejects_unverified_password_provider_email() -> None:
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "parent@example.com",
                "uid": "firebase-parent-1",
                "email_verified": False,
                "firebase": {"sign_in_provider": "password"},
            }
        ),
        users=FakeUsers(),
    )

    with pytest.raises(InvalidToken):
        await use_case.execute("firebase-token")


@pytest.mark.asyncio
async def test_register_public_parent_does_not_reactivate_disabled_user() -> None:
    existing = User(
        user_id="u-disabled",
        email="parent@example.com",
        display_name="Disabled Parent",
        roles=("parent",),
        is_active=False,
        academy_id="academy-a",
    )
    use_case = RegisterPublicParent(
        verifier=FakeVerifier({"email": "parent@example.com", "uid": "firebase-parent-1"}),
        users=FakeUsers(existing),
    )

    with pytest.raises(UserInactive):
        await use_case.execute("firebase-token")


# ---------------------------------------------------------------------------
# SaaS mode (fixes #81): resolved tenant flows through; membership upserted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_public_parent_saas_uses_resolved_tenant_not_default() -> None:
    """Issue #81 regression: in SaaS mode the resolved tenant from the
    request host must flow into User.academy_id and a matching active
    membership row must be created. The configured default_academy_id
    must NOT be used as a fallback in SaaS request paths."""
    users = FakeUsers()
    memberships = FakeMemberships()
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=users,
        memberships=memberships,
        default_academy_id="default-academy",
        saas_mode=True,
    )

    user = await use_case.execute("firebase-token", academy_id="acad_acme")

    # User row carries the resolved tenant, NOT the default fallback.
    assert user.academy_id == "acad_acme"
    assert users.ensure_calls[0]["academy_id"] == "acad_acme"

    # Public self-registration grants the verified parent enough tenant
    # access to enter onboarding. Registration application approval remains
    # a separate admin workflow.
    assert len(memberships.upserts) == 1
    upsert = memberships.upserts[0]
    assert upsert.academy_id == "acad_acme"
    assert upsert.user_id == "firebase-parent-1"
    assert upsert.roles == ("parent",)
    assert upsert.status == "active"
    assert upsert.accepted_at is not None
    assert upsert.is_active()


@pytest.mark.asyncio
async def test_register_public_parent_saas_does_not_mutate_existing_membership() -> None:
    existing = AcademyMembership(
        membership_id="membership-existing",
        academy_id="acad_acme",
        user_id="firebase-parent-1",
        roles=("parent",),
        status="active",
    )
    memberships = FakeMemberships(existing=existing)
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=FakeUsers(),
        memberships=memberships,
        saas_mode=True,
    )

    await use_case.execute("firebase-token", academy_id="acad_acme")

    assert memberships.upserts == []


@pytest.mark.asyncio
async def test_register_public_parent_saas_grants_parent_role_on_active_non_parent_membership() -> (
    None
):
    """P2: a user already active at this academy as coach/admin (no parent role)
    must have parent granted on their membership, not silently skipped — otherwise
    ensure_parent_user grants User.roles=parent globally but LoadAuthClaims/
    require_persona("parent") reads AcademyMembership.roles and /parent/onboarding
    404s despite a 'successful' registration response. Existing roles must survive."""
    existing = AcademyMembership(
        membership_id="membership-existing-coach",
        academy_id="acad_acme",
        user_id="firebase-parent-1",
        roles=("coach",),
        status="active",
    )
    memberships = FakeMemberships(existing=existing)
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=FakeUsers(),
        memberships=memberships,
        saas_mode=True,
    )

    await use_case.execute("firebase-token", academy_id="acad_acme")

    assert len(memberships.upserts) == 1
    upsert = memberships.upserts[0]
    assert upsert.membership_id == existing.membership_id
    assert set(upsert.roles) == {"coach", "parent"}
    assert upsert.status == "active"


@pytest.mark.asyncio
async def test_register_public_parent_saas_reactivates_invited_self_registration() -> None:
    existing = AcademyMembership(
        membership_id="membership-existing",
        academy_id="acad_acme",
        user_id="firebase-parent-1",
        roles=("parent",),
        status="invited",
    )
    memberships = FakeMemberships(existing=existing)
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=FakeUsers(),
        memberships=memberships,
        saas_mode=True,
    )

    await use_case.execute("firebase-token", academy_id="acad_acme")

    assert len(memberships.upserts) == 1
    upsert = memberships.upserts[0]
    assert upsert.membership_id == existing.membership_id
    assert upsert.academy_id == "acad_acme"
    assert upsert.user_id == "firebase-parent-1"
    assert upsert.roles == ("parent",)
    assert upsert.status == "active"
    assert upsert.accepted_at is not None


@pytest.mark.parametrize("status", ["suspended", "removed"])
async def test_register_public_parent_saas_does_not_reactivate_inactive_membership(
    status: str,
) -> None:
    existing = AcademyMembership(
        membership_id="membership-existing",
        academy_id="acad_acme",
        user_id="firebase-parent-1",
        roles=("parent",),
        status=status,  # type: ignore[arg-type]
    )
    memberships = FakeMemberships(existing=existing)
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=FakeUsers(),
        memberships=memberships,
        saas_mode=True,
    )

    await use_case.execute("firebase-token", academy_id="acad_acme")

    assert memberships.upserts == []


@pytest.mark.asyncio
async def test_register_public_parent_saas_requires_resolved_tenant() -> None:
    """SaaS mode must not silently fall back to default_academy_id when
    the route fails to resolve a tenant. The use case raises so the
    bug is loud."""
    use_case = RegisterPublicParent(
        verifier=FakeVerifier({"email": "new.parent@example.com", "uid": "firebase-parent-1"}),
        users=FakeUsers(),
        memberships=FakeMemberships(),
        saas_mode=True,
    )

    with pytest.raises(InvalidToken):
        await use_case.execute("firebase-token")  # no academy_id


def test_register_public_parent_saas_construction_requires_memberships() -> None:
    """In SaaS mode the memberships repository is mandatory — without it
    new parents would have no AcademyMembership row and would fail
    every subsequent authenticated request."""
    with pytest.raises(ValueError):
        RegisterPublicParent(
            verifier=FakeVerifier({}),
            users=FakeUsers(),
            saas_mode=True,
        )


@pytest.mark.asyncio
async def test_register_public_parent_emits_welcome_email_outbox_event() -> None:
    outbox = FakeOutbox()
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=FakeUsers(),
        outbox=outbox,
        default_academy_id="academy-a",
    )

    await use_case.execute("firebase-token")

    assert len(outbox.events) == 1
    event = outbox.events[0]
    assert event.name == "Identity.WelcomeEmailRequested"
    assert event.aggregate_id == "firebase-parent-1"
    assert event.academy_id == "academy-a"
    assert event.payload.email == "new.parent@example.com"


@pytest.mark.asyncio
async def test_register_public_parent_logs_welcome_email_outbox_failure(caplog) -> None:
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=FakeUsers(),
        outbox=FakeOutbox(fail=True),
        default_academy_id="academy-a",
    )

    user = await use_case.execute("firebase-token")

    assert user.user_id == "firebase-parent-1"
    assert "welcome_email_request_failed" in caplog.text
    assert "new.parent@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_register_public_parent_does_not_emit_duplicate_welcome_for_existing_user() -> None:
    existing = User(
        user_id="firebase-parent-1",
        email="new.parent@example.com",
        display_name="New Parent",
        roles=("parent",),
        is_active=True,
        academy_id="academy-a",
    )
    outbox = FakeOutbox()
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {
                "email": "new.parent@example.com",
                "uid": "firebase-parent-1",
                "name": "New Parent",
            }
        ),
        users=FakeUsers(existing),
        outbox=outbox,
        default_academy_id="academy-a",
    )

    await use_case.execute("firebase-token")

    assert outbox.events == []
