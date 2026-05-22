from __future__ import annotations

from backend.v2.interfaces.me_routes import MeResponse
from backend.v2.shared.auth.claims import AuthClaims


def _claims(**kwargs) -> AuthClaims:
    defaults = dict(
        user_id="u1",
        email="a@b.com",
        academy_id="acad1",
        roles=("admin",),
        membership_id="legacy-u1-acad1",
        platform_roles=("platform_admin",),
    )
    return AuthClaims(**{**defaults, **kwargs})


def test_me_response_includes_membership_id():
    claims = _claims()
    r = MeResponse(
        user_id=claims.user_id,
        email=claims.email,
        academy_id=claims.academy_id,
        roles=claims.roles,
        membership_id=claims.membership_id,
        platform_roles=claims.platform_roles,
    )
    assert r.membership_id == "legacy-u1-acad1"
    assert "platform_admin" in r.platform_roles


def test_me_response_membership_id_nullable():
    claims = _claims(membership_id=None, platform_roles=())
    r = MeResponse(
        user_id=claims.user_id,
        email=claims.email,
        academy_id=claims.academy_id,
        roles=claims.roles,
        membership_id=claims.membership_id,
        platform_roles=claims.platform_roles,
    )
    assert r.membership_id is None
    assert r.platform_roles == ()
