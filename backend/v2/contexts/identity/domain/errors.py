"""Identity domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class UserNotFound(DomainError):
    code = "Identity.UserNotFound"
    status_code = 404


class UserEmailAlreadyExists(DomainError):
    code = "Identity.UserEmailAlreadyExists"
    status_code = 409


class UserEmailUpdateFailed(DomainError):
    code = "Identity.UserEmailUpdateFailed"
    status_code = 502


class UserCreateFailed(DomainError):
    code = "Identity.UserCreateFailed"
    status_code = 502


class UserInactive(DomainError):
    code = "Identity.UserInactive"
    status_code = 403


class InvalidToken(DomainError):
    code = "Identity.InvalidToken"
    status_code = 401


class LoginInviteSendFailed(DomainError):
    """Raised when the set-password invite email could not be sent."""

    code = "Identity.LoginInviteSendFailed"
    status_code = 502


class MembershipNotFound(DomainError):
    """No active `academy_memberships` row for this (user, academy) pair.

    Raised by `LoadAuthClaims` when the resolved tenant has no membership
    for the authenticated user, or when the membership exists but is not
    active (invited/suspended/removed). The auth surface maps this to 403.
    """

    code = "Identity.MembershipNotFound"
    status_code = 403


class CannotRemoveLastRole(DomainError):
    """Raised when removing a role would leave the user with no roles."""

    code = "Identity.CannotRemoveLastRole"
    status_code = 409


class MagicLinkInvalid(DomainError):
    """The one-time magic-link token is unknown, already used, or tenant-mismatched.

    Deliberately generic (no distinction between "never existed", "already
    consumed", and "belongs to another tenant") so a caller cannot probe which
    tokens exist. The consume surface maps this to 401.
    """

    code = "Identity.MagicLinkInvalid"
    status_code = 401


class MagicLinkExpired(DomainError):
    """The magic-link token was valid but has passed its TTL.

    Distinct from ``MagicLinkInvalid`` so the frontend can steer the parent to
    "sign in and use Forgot password" instead of showing a generic error. The
    consume surface maps this to 410 Gone.
    """

    code = "Identity.MagicLinkExpired"
    status_code = 410
