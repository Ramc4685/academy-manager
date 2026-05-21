"""Communications domain errors."""

from __future__ import annotations


class CommunicationsError(Exception):
    """Base error for the communications context."""


class InvalidAudienceError(CommunicationsError, ValueError):
    """Raised when an audience descriptor is malformed or unknown."""


class EmptyAudienceError(CommunicationsError):
    """Raised when an audience resolves to zero recipients.

    A campaign with no recipients is almost always an admin mistake. We refuse
    to mark a campaign as 'sent' against an empty audience because the audit
    trail would imply a successful send that never happened.
    """
