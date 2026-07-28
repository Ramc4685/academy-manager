"""Identity domain models.

Pure Python (stdlib + pydantic only). No infrastructure imports.

In the SaaS v2 model (ADR-0007) identity is split:

* `User` is the **global** identity record — one per person, irrespective of
  how many academies they belong to. It carries no academy tenancy.
* `AcademyMembership` carries per-academy access (roles, status) for a user.
  A user may have zero, one, or many memberships.
* `PlatformRole` carries platform-wide (cross-tenant) capabilities such as
  `platform_admin` or `platform_support`. Platform roles are checked
  separately from academy roles.

`AuthClaims` (in `shared/auth/claims.py`) is the request-scoped value derived
from a verified token + resolved tenant + membership lookup; the bridge
between User/Membership/PlatformRole and AuthClaims is the
`load_auth_claims` use case.

Legacy single-tenant fields (`User.academy_id`, `User.roles`, `User.is_active`)
remain as optional, backwards-compatible attributes so the existing Mongo
repository and pre-SaaS use cases keep working while membership-based code
lands incrementally. SaaS request paths must not consume them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# Academy-scoped roles. These are the roles a user can hold *within* a
# single academy via an `AcademyMembership`. They are NOT platform roles.
#
# "student" (UIM12) is granted only via `ProvisionStudentLogin`, which links
# the membership's `user_id` to a `Student.student_user_id`. It is gated
# end-to-end by `settings.enable_student_login` — a `student` membership can
# exist while the flag is off (the invite already went out); the BFF just
# 404s until the flag flips.
#
# `owner` is the franchise role: a user holding it in several academies can
# read a cross-academy financial rollup (UIM11). It is still an academy-scoped
# role — the rollup unions the user's own `owner` memberships and never widens
# from the request tenant.
Role = Literal["admin", "coach", "parent", "student", "owner"]

# Platform-wide roles. Granted via `PlatformRole` records and carried on
# `AuthClaims.platform_roles` separately from academy roles.
PlatformRoleName = Literal["platform_admin", "platform_support"]

GlobalUserStatus = Literal["active", "disabled", "deleted"]
MembershipStatus = Literal["invited", "active", "suspended", "removed"]
PlatformRoleStatus = Literal["active", "revoked"]


def normalize_email(email: str) -> str:
    """Canonicalize an email for unique-index lookup."""

    return email.strip().lower()


class User(BaseModel):
    """A global identity that can sign in.

    SaaS model: a User has NO `academy_id` requirement. Per-academy access is
    represented by `AcademyMembership` records. The legacy `academy_id`,
    `roles`, and `is_active` fields are retained as optional, defaulted
    attributes so the existing Mongo repository and pre-SaaS use cases keep
    working until they migrate; they must not be consumed by SaaS request
    paths.
    """

    model_config = {"frozen": True}

    user_id: str
    firebase_uid: str | None = None
    email: EmailStr
    normalized_email: str | None = None
    display_name: str
    phone: str | None = None
    global_status: GlobalUserStatus = "active"

    # ---- Legacy single-tenant compatibility ---------------------------------
    # These are NOT the SaaS source of truth. They are kept so existing code
    # paths (mongo_user_repo, register_public_parent, single-tenant tests)
    # continue to function. SaaS paths consume AcademyMembership instead.
    roles: tuple[Role, ...] = Field(default_factory=tuple)
    is_active: bool = True
    academy_id: str | None = None

    @model_validator(mode="after")
    def _fill_normalized_email(self) -> User:
        if self.normalized_email is None:
            object.__setattr__(self, "normalized_email", normalize_email(str(self.email)))
        return self

    def has_role(self, role: Role) -> bool:
        """Legacy academy-role check.

        Retained for pre-SaaS callers. SaaS code must check membership roles
        via `AcademyMembership.has_role`, never via this method, because a
        user can hold different roles in different academies.
        """

        return role in self.roles


class AcademyMembership(BaseModel):
    """A user's access to a single academy.

    The `(academy_id, user_id)` pair is unique. Roles listed here apply
    **only** within `academy_id` — they are not platform-wide.
    """

    model_config = {"frozen": True}

    membership_id: str
    academy_id: str
    user_id: str
    roles: tuple[Role, ...] = Field(default_factory=tuple)
    status: MembershipStatus = "active"
    invited_by: str | None = None
    invited_at: datetime | None = None
    accepted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("roles")
    @classmethod
    def _dedupe_roles(cls, value: tuple[Role, ...]) -> tuple[Role, ...]:
        seen: list[Role] = []
        for role in value:
            if role not in seen:
                seen.append(role)
        return tuple(seen)

    def is_active(self) -> bool:
        return self.status == "active"

    def has_role(self, role: Role) -> bool:
        """A role only counts if the membership is active.

        An invited / suspended / removed membership grants no access even if
        the row still lists roles.
        """

        return self.is_active() and role in self.roles


class PlatformRole(BaseModel):
    """Platform-wide role grant for a user (cross-tenant capability).

    `(user_id, role)` is unique. A revoked grant does not confer the role.
    """

    model_config = {"frozen": True}

    platform_role_id: str
    user_id: str
    role: PlatformRoleName
    status: PlatformRoleStatus = "active"
    granted_by: str | None = None
    granted_at: datetime | None = None

    def is_active(self) -> bool:
        return self.status == "active"


class MagicLinkRecord(BaseModel):
    """A single-use, short-lived auto-login token for a provisioned parent.

    Only the SHA-256 hash of the emitted token is stored (``token_hash``); the
    raw token never touches the database, so a leaked collection cannot be
    replayed. ``academy_id`` binds the token to the tenant it was issued for —
    the consume use case rejects a token whose ``academy_id`` differs from the
    resolved tenant. ``used_at`` is ``None`` until the token is redeemed; the
    single-use guarantee is enforced by an atomic ``used_at=None`` conditional
    update in the repository, not by reading this field.
    """

    model_config = {"frozen": True}

    magic_link_id: str
    token_hash: str
    user_id: str
    academy_id: str
    next_path: str
    created_at: datetime
    expires_at: datetime
    purge_at: datetime
    used_at: datetime | None = None

    def is_expired(self, *, now: datetime) -> bool:
        return now >= self.expires_at
