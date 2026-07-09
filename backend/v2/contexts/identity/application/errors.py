"""Identity application-layer error re-exports.

Interface layer imports from here (allowed) rather than domain.errors (forbidden).
"""

from backend.v2.contexts.identity.domain.errors import (
    LoginInviteSendFailed,
    UserEmailAlreadyExists,
    UserNotFound,
)

__all__ = [
    "LoginInviteSendFailed",
    "UserEmailAlreadyExists",
    "UserNotFound",
]
