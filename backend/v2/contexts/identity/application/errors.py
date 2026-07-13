"""Identity application-layer error re-exports.

Interface layer imports from here (allowed) rather than domain.errors (forbidden).
"""

from backend.v2.contexts.identity.domain.errors import (
    CannotRemoveLastRole,
    LoginInviteSendFailed,
    UserEmailAlreadyExists,
    UserNotFound,
)

__all__ = [
    "CannotRemoveLastRole",
    "LoginInviteSendFailed",
    "UserEmailAlreadyExists",
    "UserNotFound",
]
