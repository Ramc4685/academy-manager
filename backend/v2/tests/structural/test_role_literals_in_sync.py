"""The academy Role literal exists twice and the copies must stay equal.

``shared/auth/claims.Role`` mirrors ``contexts/identity/domain/models.Role``
by hand (``shared`` may not import ``contexts``). A role added to one and not
the other makes membership rows holding it fail to deserialize into
``AuthClaims`` and locks those users out (UIM12 postmortem). The staff tiers
of #553 (``billing``, ``front_desk``) are the latest addition.
"""

from __future__ import annotations

import typing

from backend.v2.contexts.identity.domain.models import Role as IdentityRole
from backend.v2.interfaces.admin.directory_routes import AdminRole
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.auth.claims import Role as ClaimsRole


def test_claims_role_equals_identity_role() -> None:
    assert set(typing.get_args(ClaimsRole)) == set(typing.get_args(IdentityRole))


def test_staff_tiers_are_academy_roles() -> None:
    assert {"billing", "front_desk"} <= set(typing.get_args(IdentityRole))


def test_every_academy_role_but_student_is_manageable_from_the_directory() -> None:
    # Students get their login only via ProvisionStudentLogin (UIM12).
    assert set(typing.get_args(AdminRole)) == set(typing.get_args(IdentityRole)) - {"student"}


def test_a_staff_tier_membership_deserializes_into_auth_claims() -> None:
    for role in ("billing", "front_desk"):
        claims = AuthClaims(user_id="u", email="u@example.com", academy_id="a", roles=(role,))
        assert claims.has_role(role)
