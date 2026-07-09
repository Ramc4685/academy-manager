"""Identity application-layer error re-exports.

Interface layer imports from here (allowed) rather than domain.errors (forbidden).
"""

from backend.v2.contexts.identity.domain.errors import UserEmailAlreadyExists, UserNotFound

__all__ = [
    "UserEmailAlreadyExists",
    "UserNotFound",
    "CannotRemoveLastRole",
]


class CannotRemoveLastRole(Exception):
    """Raised when removing a role would leave the user with no roles."""
