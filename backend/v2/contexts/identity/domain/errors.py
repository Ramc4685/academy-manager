"""Identity domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class UserNotFound(DomainError):
    code = "Identity.UserNotFound"
    status_code = 404


class UserInactive(DomainError):
    code = "Identity.UserInactive"
    status_code = 403


class InvalidToken(DomainError):
    code = "Identity.InvalidToken"
    status_code = 401


class MembershipNotFound(DomainError):
    """No active `academy_memberships` row for this (user, academy) pair.

    Raised by `LoadAuthClaims` when the resolved tenant has no membership
    for the authenticated user, or when the membership exists but is not
    active (invited/suspended/removed). The auth surface maps this to 403.
    """

    code = "Identity.MembershipNotFound"
    status_code = 403
