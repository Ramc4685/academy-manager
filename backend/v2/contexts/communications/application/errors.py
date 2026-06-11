"""Communications application-layer error/model re-exports.

Interface layer imports from here (allowed) rather than domain (forbidden).
"""

from backend.v2.contexts.communications.domain.errors import EmptyAudienceError
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    SessionAudience,
)

__all__ = [
    "AcademyAudience",
    "EmptyAudienceError",
    "SessionAudience",
]
