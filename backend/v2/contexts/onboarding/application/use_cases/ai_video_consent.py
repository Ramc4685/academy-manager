"""Per-child AI/video consent use cases (AI strategy Phase 3, slice E1).

Stored and unused: no model, no upload, no clip. ``ConsentAiVideo`` is the one
read path every later video slice must call before it touches a child's clip.
It returns False unless the child has an active, non-revoked consent to the
current text, and always False while that text is the placeholder
(``ai_video_consent_v0_placeholder``), so placeholder consent can never
authorize real use.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.domain.ai_video_consent import (
    AI_VIDEO_CONSENT_TEXT,
    AI_VIDEO_CONSENT_TEXT_VERSION,
    AiVideoConsent,
    authorizes,
    is_placeholder_version,
)
from backend.v2.contexts.onboarding.domain.errors import (
    AiVideoConsentIncomplete,
    AiVideoConsentTextChanged,
    WaiverStudentNotFound,
)

# Re-exported for the interface layer (ADR-0005 rule 4).
__all__ = ["AI_VIDEO_CONSENT_TEXT", "AI_VIDEO_CONSENT_TEXT_VERSION"]

AiVideoConsentChildStatus = Literal["granted", "revoked", "none"]


class AiVideoConsentChild(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str


class AiVideoConsentRow(BaseModel):
    """One child's consent status, as the parent and the admin see it."""

    model_config = {"frozen": True}

    student_id: str
    student_name: str
    status: AiVideoConsentChildStatus
    text_version: str | None = None
    accepted_at: datetime | None = None
    accepted_by: str | None = None
    revoked_at: datetime | None = None


class ParentAiVideoConsentView(BaseModel):
    model_config = {"frozen": True}

    text_version: str
    text: str
    #: True while the text is the unreviewed placeholder: consent then authorizes nothing.
    placeholder: bool
    children: list[AiVideoConsentRow]


class AiVideoConsentRepository(Protocol):
    async def children_of(self, parent_id: str) -> list[AiVideoConsentChild]: ...
    async def consents_for(self, student_ids: list[str]) -> dict[str, AiVideoConsent]: ...
    async def save_grant(self, consent: AiVideoConsent) -> None: ...
    async def save_revoke(self, student_id: str, *, revoked_at: datetime, revoked_by: str) -> None:
        """Record a revocation of the active consent; a no-op when none is active."""
        ...

    async def list_all(self) -> list[tuple[AiVideoConsent, str]]:
        """Every consent record in the academy in scope, with the child's name."""
        ...

    async def get_for_academy(self, academy_id: str, student_id: str) -> AiVideoConsent | None:
        """Explicit academy: the read path also serves jobs with no request scope."""
        ...


def _row(child: AiVideoConsentChild, consent: AiVideoConsent | None) -> AiVideoConsentRow:
    if consent is None:
        return AiVideoConsentRow(
            student_id=child.student_id, student_name=child.student_name, status="none"
        )
    return AiVideoConsentRow(
        student_id=child.student_id,
        student_name=child.student_name,
        status=consent.status,
        text_version=consent.text_version,
        accepted_at=consent.accepted_at,
        accepted_by=consent.accepted_by,
        revoked_at=consent.revoked_at,
    )


class ParentAiVideoConsent:
    """The parent's opt-in, read and revoke for their own children."""

    def __init__(
        self,
        *,
        consents: AiVideoConsentRepository,
        clock: Callable[[], datetime] | None = None,
        text_version: str = AI_VIDEO_CONSENT_TEXT_VERSION,
        text: str = AI_VIDEO_CONSENT_TEXT,
    ) -> None:
        self._consents = consents
        self._clock = clock or (lambda: datetime.now(UTC))
        self._version = text_version
        self._text = text

    async def get(self, *, parent_id: str) -> ParentAiVideoConsentView:
        children = await self._consents.children_of(parent_id)
        stored = await self._consents.consents_for([child.student_id for child in children])
        return ParentAiVideoConsentView(
            text_version=self._version,
            text=self._text,
            placeholder=is_placeholder_version(self._version),
            children=[_row(child, stored.get(child.student_id)) for child in children],
        )

    async def grant(
        self,
        *,
        parent_id: str,
        student_id: str,
        text_version: str,
        consent: bool,
        signer_email: str | None,
    ) -> ParentAiVideoConsentView:
        await self._own_child(parent_id, student_id)
        if not consent:
            raise AiVideoConsentIncomplete("Tick the box to give AI/video consent.")
        if text_version != self._version:
            raise AiVideoConsentTextChanged(
                "The consent text changed. Reload the page and read it again."
            )
        await self._consents.save_grant(
            AiVideoConsent(
                student_id=student_id,
                status="granted",
                text_version=self._version,
                accepted_at=self._clock(),
                accepted_by=parent_id,
                accepted_by_email=signer_email,
            )
        )
        return await self.get(parent_id=parent_id)

    async def revoke(self, *, parent_id: str, student_id: str) -> ParentAiVideoConsentView:
        await self._own_child(parent_id, student_id)
        await self._consents.save_revoke(student_id, revoked_at=self._clock(), revoked_by=parent_id)
        return await self.get(parent_id=parent_id)

    async def _own_child(self, parent_id: str, student_id: str) -> None:
        children = await self._consents.children_of(parent_id)
        if student_id not in {child.student_id for child in children}:
            # 404, not 403: another family's child id must not be probeable.
            raise WaiverStudentNotFound("Child not found")


class ListAdminAiVideoConsents:
    """Read-only per-child consent status for the admin waivers page."""

    def __init__(self, *, consents: AiVideoConsentRepository) -> None:
        self._consents = consents

    async def execute(self) -> list[AiVideoConsentRow]:
        rows = [
            _row(AiVideoConsentChild(student_id=consent.student_id, student_name=name), consent)
            for consent, name in await self._consents.list_all()
        ]
        return sorted(rows, key=lambda row: row.student_name.lower())


class ConsentAiVideo:
    """``consent_ai_video(academy_id, student_id) -> bool``: the only video gate.

    Every later video slice (E2 real clips, E3 capture and the deletion job)
    must call this before touching a child's clip. False unless the child has
    an active, non-revoked consent to the current text version. Always False
    while the current text is a placeholder: placeholder consent can never
    authorize real use, however many parents ticked the box.
    """

    def __init__(
        self,
        *,
        consents: AiVideoConsentRepository,
        text_version: str = AI_VIDEO_CONSENT_TEXT_VERSION,
    ) -> None:
        self._consents = consents
        self._version = text_version

    async def execute(self, academy_id: str, student_id: str) -> bool:
        if not academy_id or not student_id or is_placeholder_version(self._version):
            return False
        consent = await self._consents.get_for_academy(academy_id, student_id)
        return authorizes(consent, self._version)

    __call__ = execute
