"""Per-child AI/video consent (AI strategy Phase 3, slice E1).

A parent opts one child in to AI analysis of coaching video, against a
versioned consent text (version, accepted at, accepted by, like the platform
agreement). The parent can revoke at any time; the revocation is recorded.

Nothing reads video yet. Every later video slice must ask ``authorizes`` (via
the ``ConsentAiVideo`` read path) before touching a child's clip, and it is
False unless the child has an active, non-revoked consent to the *current*
text, and that text is not a placeholder. The shipped text IS a placeholder,
so today no consent authorizes anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

#: PLACEHOLDER. Needs counsel review before any use. The owner replaces this
#: text after counsel and bumps the version to one without "placeholder".
AI_VIDEO_CONSENT_TEXT_VERSION = "ai_video_consent_v0_placeholder"

AI_VIDEO_CONSENT_TEXT = (
    "PLACEHOLDER TEXT, NOT REVIEWED BY COUNSEL. "
    "I agree that short coaching video clips of my child may be analysed by an AI "
    "model from [vendor to be confirmed] to help the coach review technique. "
    "Only the coach sees the AI's suggestions, and a coach approves anything shared "
    "with me. Raw clips are deleted [30, 60 or 90] days after they are recorded. "
    "I can withdraw this consent at any time from the parent app, and no new clip "
    "of my child will be analysed after I do."
)

AiVideoConsentStatus = Literal["granted", "revoked"]


def is_placeholder_version(text_version: str | None) -> bool:
    """A placeholder text can never authorize real use, whatever was clicked."""
    return not text_version or "placeholder" in text_version


class AiVideoConsent(BaseModel):
    """The current consent state for one child in one academy."""

    model_config = {"frozen": True}

    student_id: str
    status: AiVideoConsentStatus
    text_version: str
    accepted_at: datetime
    accepted_by: str  # the parent's user id
    accepted_by_email: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None


def authorizes(
    consent: AiVideoConsent | None,
    current_version: str = AI_VIDEO_CONSENT_TEXT_VERSION,
) -> bool:
    """True only for an active consent to the current, non-placeholder text."""
    return (
        consent is not None
        and consent.status == "granted"
        and consent.revoked_at is None
        and consent.text_version == current_version
        and not is_placeholder_version(current_version)
    )
