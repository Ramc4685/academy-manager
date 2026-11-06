"""Wiring for per-child AI/video consent (AI strategy Phase 3, slice E1).

``compose_consent_ai_video`` is the read path every later video slice must
wire in: ``await consent_ai_video(academy_id, student_id) -> bool``. It is
False unless the child has an active, non-revoked consent to the current
text, and always False while the text is the placeholder.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.onboarding.application.use_cases.ai_video_consent import (
    ConsentAiVideo,
    ListAdminAiVideoConsents,
    ParentAiVideoConsent,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_ai_video_consent_repo import (
    MongoAiVideoConsentRepository,
)


def compose_parent_ai_video_consent(db: Any) -> ParentAiVideoConsent:
    return ParentAiVideoConsent(consents=MongoAiVideoConsentRepository(db))


def compose_admin_ai_video_consents(db: Any) -> ListAdminAiVideoConsents:
    return ListAdminAiVideoConsents(consents=MongoAiVideoConsentRepository(db))


def compose_consent_ai_video(db: Any) -> ConsentAiVideo:
    return ConsentAiVideo(consents=MongoAiVideoConsentRepository(db))
