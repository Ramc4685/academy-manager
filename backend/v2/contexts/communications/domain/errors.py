"""Communications domain errors."""

from __future__ import annotations


class CommunicationsError(Exception):
    """Base error for the communications context."""


class InvalidAudienceError(CommunicationsError, ValueError):
    """Raised when an audience descriptor is malformed or unknown."""


class DuplicateCampaignError(CommunicationsError):
    """Raised when a campaign idempotency claim is lost to a concurrent send
    and the winning campaign cannot be read back.

    This is a should-never-happen race guard: normally a lost claim resolves
    to the existing campaign and the caller gets a deduplicated result.
    """


class EmptyAudienceError(CommunicationsError):
    """Raised when an audience resolves to zero recipients.

    A campaign with no recipients is almost always an admin mistake. We refuse
    to mark a campaign as 'sent' against an empty audience because the audit
    trail would imply a successful send that never happened.
    """


class InvalidProviderSignature(CommunicationsError):
    """Raised when an inbound provider webhook fails signature verification.

    Mapped to HTTP 401 by the webhook route. Nothing is written before the
    signature is checked, so a forged or replayed request leaves no trace in
    the suppression list or the event log.
    """
