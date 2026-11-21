"""Communications application-layer error/model re-exports.

Interface layer imports from here (allowed) rather than domain (forbidden).
"""

from backend.v2.contexts.communications.domain.errors import (
    AudienceChangedError,
    DuplicateCampaignError,
    EmptyAudienceError,
    InvalidAudienceError,
    InvalidProviderSignature,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    SessionAudience,
    SessionsAudience,
)

__all__ = [
    "AcademyAudience",
    "AudienceChangedError",
    "DuplicateCampaignError",
    "EmptyAudienceError",
    "InvalidAudienceError",
    "InvalidProviderSignature",
    "SessionAudience",
    "SessionsAudience",
]
