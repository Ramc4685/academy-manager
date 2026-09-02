"""Identity application-layer error re-exports.

Interface layer imports from here (allowed) rather than domain.errors (forbidden).
"""

from backend.v2.contexts.identity.domain.errors import (
    CannotRemoveLastRole,
    InvalidToken,
    LoginInviteSendFailed,
    UserEmailAlreadyExists,
    UserNotFound,
    VerificationEmailThrottled,
)

__all__ = [
    "CannotRemoveLastRole",
    "InvalidToken",
    "LoginInviteSendFailed",
    "UserEmailAlreadyExists",
    "UserNotFound",
    "VerificationEmailThrottled",
]
