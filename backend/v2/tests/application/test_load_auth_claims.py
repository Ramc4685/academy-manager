"""Use-case tests for LoadAuthClaims with port fakes.

SaaS shape (ADR-0007):

* Token is verified → global user lookup by email.
* Tenant is supplied by the caller (TenancyMiddleware resolved it from
  domain/subdomain). LoadAuthClaims must NEVER fall back to
  ``settings.default_academy_id`` or the user's legacy ``academy_id``.
* Active ``academy_memberships`` row is required for the resolved
  academy; missing/inactive memberships raise ``MembershipNotFound``.
* Platform roles are loaded separately from academy roles.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.load_auth_claims import (
    LoadAuthClaims,
)
from backend.v2.contexts.identity.domain.errors import (
    InvalidToken,
    MembershipNotFound,
    UserInactive,
    UserNotFound,
)
from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    PlatformRole,
    User,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeVerifier:
    def __init__(
        self,
        claims: dict[str, object] | None = None,
        raise_with: Exception | None = None,
    ) -> None:
        self._claims = claims
        self._raise = raise_with

    async def verify(self, id_token: str) -> dict[str, object]:
        if self._raise:
            raise self._raise
        return dict(self._claims or {})


class FakeUserRepo:
    def __init__(self, users: list[User]) -> None:
        self._by_email = {str(u.email): u for u in users}

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)

    async def get_by_id(self, user_id: str) -> User | None:
        for u in self._by_email.values():
            if u.user_id == user_id:
                return u
        return None


class FakeMembershipRepo:
    def __init__(self, memberships: list[AcademyMembership]) -> None:
        self._rows = list(memberships)

    async def get_for_user_in_academy(
        self, *, user_id: str, academy_id: str, aliases=None
    ) -> AcademyMembership | None:
        candidates = {user_id, *(aliases or ())}
        for row in self._rows:
            if row.user_id in candidates and row.academy_id == academy_id:
                return row
        return None


class FakePlatformRoleRepo:
    def __init__(self, grants: list[PlatformRole]) -> None:
        self._rows = list(grants)

    async def list_active_for_user(self, user_id: str) -> list[PlatformRole]:
        return [r for r in self._rows if r.user_id == user_id and r.is_active()]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _coach_user() -> User:
    return User(
        user_id="u-coach",
        email="coach@example.com",
        display_name="Coach Carter",
        global_status="active",
        # Legacy single-tenant fields — SaaS path must IGNORE these.
        roles=("coach",),
        is_active=True,
        academy_id="legacy-default-academy",
    )


def _coach_membership(academy_id: str = "academy-court") -> AcademyMembership:
    return AcademyMembership(
        membership_id="m-coach-court",
        academy_id=academy_id,
        user_id="u-coach",
        roles=("coach",),
        status="active",
    )


def _build(
    *,
    token_email: str | None = "coach@example.com",
    token_claims: dict[str, object] | None = None,
    users: list[User] | None = None,
    memberships: list[AcademyMembership] | None = None,
    platform_roles: list[PlatformRole] | None = None,
    verifier_error: Exception | None = None,
) -> LoadAuthClaims:
    return LoadAuthClaims(
        verifier=FakeVerifier(
            claims=(
                token_claims
                if token_claims is not None
                else ({"email": token_email} if token_email is not None else {})
            ),
            raise_with=verifier_error,
        ),
        users=FakeUserRepo(users if users is not None else [_coach_user()]),
        memberships=FakeMembershipRepo(
            memberships if memberships is not None else [_coach_membership()]
        ),
        platform_roles=FakePlatformRoleRepo(platform_roles or []),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_token_valid_tenant_active_membership_returns_claims() -> None:
    uc = _build()
    claims = await uc.execute("fake-token", resolved_academy_id="academy-court")
    assert claims.user_id == "u-coach"
    assert claims.email == "coach@example.com"
    assert claims.academy_id == "academy-court"
    assert claims.membership_id == "m-coach-court"
    assert claims.roles == ("coach",)
    assert claims.platform_roles == ()


@pytest.mark.asyncio
async def test_membership_keyed_by_firebase_alias_still_resolves_claims() -> None:
    """Regression (#424): the membership row is keyed by the provisioned
    `firebase_uid` while the users doc keeps its roster `user_id`
    (`ensure_parent_login` writes exactly this shape). The login path matched
    `user_id` only, so such a parent signed in to Firebase and then got a bare
    401 from `/api/v2/me`. PR #400 already fixed the invite path the same way."""
    parent = User(
        user_id="roster-parent-7",
        firebase_uid="fb-uid-7",
        email="parent@example.com",
        display_name="Roster Parent",
        global_status="active",
    )
    membership = AcademyMembership(
        membership_id="m-parent-alias",
        academy_id="academy-court",
        user_id="fb-uid-7",  # keyed by the alias, not users.user_id
        roles=("parent",),
        status="active",
    )
    uc = _build(token_email="parent@example.com", users=[parent], memberships=[membership])

    claims = await uc.execute("fake-token", resolved_academy_id="academy-court")

    assert claims.membership_id == "m-parent-alias"
    assert claims.roles == ("parent",)
    assert claims.user_id == "roster-parent-7"
    assert claims.academy_id == "academy-court"


@pytest.mark.asyncio
async def test_alias_match_does_not_cross_academies() -> None:
    """Alias matching widens identity, never tenant scope."""
    parent = User(
        user_id="roster-parent-7",
        firebase_uid="fb-uid-7",
        email="parent@example.com",
        display_name="Roster Parent",
        global_status="active",
    )
    other_academy_membership = AcademyMembership(
        membership_id="m-elsewhere",
        academy_id="academy-other",
        user_id="fb-uid-7",
        roles=("parent",),
        status="active",
    )
    uc = _build(
        token_email="parent@example.com",
        users=[parent],
        memberships=[other_academy_membership],
    )

    with pytest.raises(MembershipNotFound):
        await uc.execute("fake-token", resolved_academy_id="academy-court")


@pytest.mark.asyncio
async def test_claims_use_resolved_tenant_not_user_legacy_academy_id() -> None:
    """SaaS path must NEVER fall back to user.academy_id / default_academy_id."""
    uc = _build()
    claims = await uc.execute("fake-token", resolved_academy_id="academy-court")
    # User's legacy academy_id is `legacy-default-academy`; claims must NOT use it.
    assert claims.academy_id == "academy-court"
    assert claims.academy_id != "legacy-default-academy"


# ---------------------------------------------------------------------------
# Token / user failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_token_raised() -> None:
    uc = _build(verifier_error=ValueError("bad sig"))
    with pytest.raises(InvalidToken):
        await uc.execute("bad", resolved_academy_id="academy-court")


@pytest.mark.asyncio
async def test_missing_email_raises() -> None:
    uc = _build(token_email=None)
    with pytest.raises(InvalidToken):
        await uc.execute("ok", resolved_academy_id="academy-court")


@pytest.mark.asyncio
async def test_password_provider_requires_verified_email() -> None:
    uc = _build(
        token_claims={
            "email": "coach@example.com",
            "email_verified": False,
            "firebase": {"sign_in_provider": "password"},
        }
    )
    with pytest.raises(InvalidToken):
        await uc.execute("ok", resolved_academy_id="academy-court")


@pytest.mark.asyncio
async def test_social_provider_does_not_require_email_verified_claim() -> None:
    uc = _build(
        token_claims={
            "email": "coach@example.com",
            "firebase": {"sign_in_provider": "google.com"},
        }
    )
    claims = await uc.execute("ok", resolved_academy_id="academy-court")
    assert claims.user_id == "u-coach"


@pytest.mark.asyncio
async def test_unknown_user_raises_not_found() -> None:
    uc = _build(token_email="ghost@example.com")
    with pytest.raises(UserNotFound):
        await uc.execute("ok", resolved_academy_id="academy-court")


@pytest.mark.asyncio
async def test_inactive_user_raises() -> None:
    inactive = _coach_user().model_copy(update={"global_status": "disabled"})
    uc = _build(users=[inactive])
    with pytest.raises(UserInactive):
        await uc.execute("ok", resolved_academy_id="academy-court")


# ---------------------------------------------------------------------------
# Membership enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_membership_for_resolved_academy_rejects() -> None:
    """Valid user with NO membership for the resolved academy → rejected."""
    uc = _build(memberships=[])
    with pytest.raises(MembershipNotFound):
        await uc.execute("ok", resolved_academy_id="academy-court")


@pytest.mark.asyncio
async def test_inactive_membership_rejects() -> None:
    suspended = _coach_membership().model_copy(update={"status": "suspended"})
    uc = _build(memberships=[suspended])
    with pytest.raises(MembershipNotFound):
        await uc.execute("ok", resolved_academy_id="academy-court")


@pytest.mark.asyncio
async def test_membership_for_other_academy_does_not_count() -> None:
    """Membership in academy A must NOT grant access when tenant is academy B."""
    other = _coach_membership(academy_id="academy-tennis")
    uc = _build(memberships=[other])
    with pytest.raises(MembershipNotFound):
        await uc.execute("ok", resolved_academy_id="academy-court")


# ---------------------------------------------------------------------------
# Platform roles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_role_included_separately_from_academy_roles() -> None:
    """Platform roles must not leak into ``roles`` — they live on
    ``platform_roles``."""
    grant = PlatformRole(
        platform_role_id="pr-1",
        user_id="u-coach",
        role="platform_admin",
        status="active",
    )
    uc = _build(platform_roles=[grant])
    claims = await uc.execute("fake-token", resolved_academy_id="academy-court")
    assert claims.platform_roles == ("platform_admin",)
    # Academy-scoped roles still come from the membership only.
    assert claims.roles == ("coach",)
    assert "platform_admin" not in claims.roles


@pytest.mark.asyncio
async def test_revoked_platform_role_not_included() -> None:
    revoked = PlatformRole(
        platform_role_id="pr-1",
        user_id="u-coach",
        role="platform_admin",
        status="revoked",
    )
    uc = _build(platform_roles=[revoked])
    claims = await uc.execute("fake-token", resolved_academy_id="academy-court")
    assert claims.platform_roles == ()


# ---------------------------------------------------------------------------
# No default_academy_id fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_requires_resolved_academy_id() -> None:
    """LoadAuthClaims must refuse to construct claims without a resolved
    tenant. Missing/empty resolved_academy_id => InvalidToken-style refusal."""
    uc = _build()
    with pytest.raises((MembershipNotFound, ValueError)):
        # Empty academy must not be silently accepted, and must not fall back
        # to the user's legacy academy_id.
        await uc.execute("fake-token", resolved_academy_id="")
