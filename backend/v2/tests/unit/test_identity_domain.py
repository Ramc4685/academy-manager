"""Pure domain tests for Identity.

Covers both the legacy single-tenant `User` surface (kept for backwards
compatibility with the pre-SaaS Mongo repository) and the new SaaS
membership-based contract from ADR-0007: global users, per-academy
`AcademyMembership`, separate `PlatformRole` grants, and an `AuthClaims`
value object that carries `membership_id` plus distinct academy and
platform role tuples.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    PlatformRole,
    User,
    normalize_email,
)
from backend.v2.shared.auth.claims import AuthClaims

# ---------------------------------------------------------------------------
# User (legacy single-tenant compatibility)
# ---------------------------------------------------------------------------


def _user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "user_id": "u1",
        "email": "coach@example.com",
        "display_name": "Coach Carter",
        "roles": ("coach",),
        "is_active": True,
        "academy_id": "test-academy",
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


def test_user_is_frozen() -> None:
    user = _user()
    with pytest.raises(ValidationError):
        user.roles = ("admin",)  # type: ignore[misc]


def test_has_role() -> None:
    user = _user(roles=("coach", "admin"))
    assert user.has_role("coach")
    assert user.has_role("admin")
    assert not user.has_role("parent")


def test_email_validation() -> None:
    with pytest.raises(ValidationError):
        _user(email="not-an-email")


# ---------------------------------------------------------------------------
# User in the SaaS shape (no academy_id required)
# ---------------------------------------------------------------------------


def test_user_can_be_constructed_without_academy_id_in_saas_model() -> None:
    """ADR-0007: User is global identity, not tenant-scoped.

    A user must be representable without any academy at all (e.g. a brand
    new sign-up before they accept an invitation, a platform admin, a
    parent enrolling at multiple academies). The legacy single-tenant
    `academy_id` field is optional and defaults to None.
    """

    user = User(
        user_id="u-saas",
        email="globally@example.com",
        display_name="Global User",
    )

    assert user.academy_id is None
    assert user.roles == ()
    assert user.global_status == "active"
    assert user.is_active is True


def test_user_normalizes_email_for_unique_lookup() -> None:
    user = User(
        user_id="u-norm",
        email="MixedCase@Example.COM",
        display_name="Norm",
    )
    assert user.normalized_email == "mixedcase@example.com"
    assert normalize_email("  Whitespace@Example.com  ") == "whitespace@example.com"


def test_user_carries_firebase_uid_and_phone_when_provided() -> None:
    user = User(
        user_id="u-fb",
        firebase_uid="fb-uid-123",
        email="fb@example.com",
        display_name="FB User",
        phone="+15551234567",
        global_status="active",
    )
    assert user.firebase_uid == "fb-uid-123"
    assert user.phone == "+15551234567"


def test_user_global_status_disabled_is_distinguishable_from_active() -> None:
    active = User(user_id="u-1", email="a@example.com", display_name="A")
    disabled = User(
        user_id="u-2",
        email="b@example.com",
        display_name="B",
        global_status="disabled",
    )
    assert active.global_status == "active"
    assert disabled.global_status == "disabled"


# ---------------------------------------------------------------------------
# AcademyMembership
# ---------------------------------------------------------------------------


def _membership(**overrides: object) -> AcademyMembership:
    defaults: dict[str, object] = {
        "membership_id": "m-1",
        "academy_id": "acad-1",
        "user_id": "u-1",
        "roles": ("coach",),
        "status": "active",
    }
    defaults.update(overrides)
    return AcademyMembership(**defaults)  # type: ignore[arg-type]


def test_membership_is_frozen() -> None:
    membership = _membership()
    with pytest.raises(ValidationError):
        membership.roles = ("admin",)  # type: ignore[misc]


def test_active_membership_has_role_grants_listed_roles() -> None:
    membership = _membership(roles=("coach", "admin"))
    assert membership.is_active()
    assert membership.has_role("coach")
    assert membership.has_role("admin")
    assert not membership.has_role("parent")


def test_membership_dedupes_roles() -> None:
    membership = _membership(roles=("coach", "coach", "admin"))
    assert membership.roles == ("coach", "admin")


def test_membership_optional_invitation_audit_fields() -> None:
    now = datetime(2026, 5, 21, tzinfo=UTC)
    membership = _membership(
        status="invited",
        invited_by="u-admin",
        invited_at=now,
        accepted_at=None,
    )
    assert membership.invited_by == "u-admin"
    assert membership.invited_at == now
    assert membership.accepted_at is None


@pytest.mark.parametrize("status", ["invited", "suspended", "removed"])
def test_inactive_membership_is_distinguishable_and_grants_no_roles(
    status: str,
) -> None:
    """A non-active membership row must never confer roles, even if `roles`
    is non-empty. This is the core SaaS invariant — an invited or suspended
    user listed as `coach` cannot act as a coach.
    """

    membership = _membership(roles=("coach", "admin"), status=status)
    assert not membership.is_active()
    assert not membership.has_role("coach")
    assert not membership.has_role("admin")


def test_two_memberships_for_same_user_can_have_different_roles_per_academy() -> None:
    """Different academies, different roles — the multi-tenant case ADR-0007
    is built to support."""

    m1 = _membership(
        membership_id="m-a", academy_id="acad-a", user_id="u-1", roles=("coach",)
    )
    m2 = _membership(
        membership_id="m-b", academy_id="acad-b", user_id="u-1", roles=("admin",)
    )
    assert m1.has_role("coach") and not m1.has_role("admin")
    assert m2.has_role("admin") and not m2.has_role("coach")


# ---------------------------------------------------------------------------
# PlatformRole
# ---------------------------------------------------------------------------


def test_platform_role_active_grant_is_distinct_from_revoked() -> None:
    active = PlatformRole(
        platform_role_id="pr-1",
        user_id="u-1",
        role="platform_admin",
        status="active",
    )
    revoked = PlatformRole(
        platform_role_id="pr-2",
        user_id="u-1",
        role="platform_support",
        status="revoked",
    )
    assert active.is_active()
    assert not revoked.is_active()


def test_platform_role_is_frozen() -> None:
    grant = PlatformRole(
        platform_role_id="pr-1",
        user_id="u-1",
        role="platform_admin",
    )
    with pytest.raises(ValidationError):
        grant.status = "revoked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AuthClaims
# ---------------------------------------------------------------------------


def test_auth_claims_carries_membership_id() -> None:
    """SaaS auth claims must carry the membership id that proved access to
    the resolved academy. Downstream guards rely on this to audit which
    membership granted the request's roles."""

    claims = AuthClaims(
        user_id="u-1",
        email="coach@example.com",
        academy_id="acad-1",
        membership_id="m-123",
        roles=("coach",),
    )
    assert claims.membership_id == "m-123"
    assert claims.academy_id == "acad-1"


def test_auth_claims_membership_id_defaults_to_none_for_legacy_callers() -> None:
    """The legacy `load_auth_claims` use case (pre-SaaS) constructs
    AuthClaims without `membership_id`; that must keep working until the
    SaaS resolver lands."""

    claims = AuthClaims(
        user_id="u-1",
        email="coach@example.com",
        academy_id="acad-1",
        roles=("coach",),
    )
    assert claims.membership_id is None
    assert claims.platform_roles == ()


def test_auth_claims_separates_academy_roles_from_platform_roles() -> None:
    """`has_role` must only consider academy roles. Platform-wide
    capabilities flow exclusively through `has_platform_role` /
    `is_platform_admin` so an admin guard on an academy route does not
    accidentally accept a platform_admin who has no membership."""

    claims = AuthClaims(
        user_id="u-platform",
        email="ops@example.com",
        academy_id="acad-1",
        membership_id="m-1",
        roles=("parent",),
        platform_roles=("platform_admin",),
    )

    # platform_admin grants no academy roles
    assert not claims.has_role("admin")
    assert not claims.has_role("coach")
    assert claims.has_role("parent")

    # platform role surfaces only via the platform helpers
    assert claims.has_platform_role("platform_admin")
    assert claims.is_platform_admin()
    assert not claims.has_platform_role("platform_support")


def test_auth_claims_academy_role_holder_is_not_a_platform_admin() -> None:
    claims = AuthClaims(
        user_id="u-acad-admin",
        email="admin@example.com",
        academy_id="acad-1",
        membership_id="m-1",
        roles=("admin",),
    )
    assert claims.has_role("admin")
    assert not claims.is_platform_admin()
    assert not claims.has_platform_role("platform_admin")


def test_auth_claims_is_frozen() -> None:
    claims = AuthClaims(
        user_id="u-1",
        email="x@example.com",
        academy_id="acad-1",
    )
    with pytest.raises(ValidationError):
        claims.roles = ("admin",)  # type: ignore[misc]
