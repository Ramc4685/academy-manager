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
    def __init__(self) -> None:
        self.upserts: list[AcademyMembership] = []

    async def upsert_membership(self, membership: AcademyMembership) -> AcademyMembership:
        self.upserts.append(membership)
        return membership

    async def get_membership(self, academy_id: str, user_id: str):  # pragma: no cover
        return None

    async def list_memberships_for_user(self, user_id: str):  # pragma: no cover
        return []

    async def list_active_platform_roles(self, user_id: str):  # pragma: no cover
        return []

    async def upsert_platform_role(self, platform_role):  # pragma: no cover
        return platform_role


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

    # Membership row created so SaaS paths can authorize the parent
    # against acad_acme on subsequent requests.
    assert len(memberships.upserts) == 1
    upsert = memberships.upserts[0]
    assert upsert.academy_id == "acad_acme"
    assert upsert.user_id == "firebase-parent-1"
    assert upsert.roles == ("parent",)
    assert upsert.is_active()


@pytest.mark.asyncio
async def test_register_public_parent_saas_requires_resolved_tenant() -> None:
    """SaaS mode must not silently fall back to default_academy_id when
    the route fails to resolve a tenant. The use case raises so the
    bug is loud."""
    use_case = RegisterPublicParent(
        verifier=FakeVerifier(
            {"email": "new.parent@example.com", "uid": "firebase-parent-1"}
        ),
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
