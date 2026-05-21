"""Waiver signature use cases (Wave 4).

The headline workflow is ``GetExactSignedWaiver``: given a ``student_id``,
return the most recent signature, the template version it pins to, the
captured ``content_hash``, and the ``artifact_id`` of the stored signed
document.

The use case enforces two integrity guarantees:

1. If the signature points to a ``waiver_template_id`` that no longer exists,
   raise ``SignedWaiverNotFound``. We don't fabricate a partial answer.
2. If the signature's captured ``content_hash`` doesn't match the referenced
   template's current ``content_hash``, return the result with
   ``signature_matches_template = False`` so admins / audits can flag the
   discrepancy.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.domain.models import (
    WaiverSignature,
    WaiverTemplate,
)


class SignedWaiverNotFound(Exception):
    """Raised when a student has no signature, or the signature dangles."""


class WaiverSignatureRepository(Protocol):
    async def latest_for_student(
        self, student_id: str
    ) -> WaiverSignature | None: ...


class WaiverTemplateRepository(Protocol):
    async def get(self, waiver_template_id: str) -> WaiverTemplate | None: ...


class ExactSignedWaiver(BaseModel):
    model_config = {"frozen": True}

    signature: WaiverSignature
    template: WaiverTemplate
    artifact_id: str | None
    signature_matches_template: bool


class GetExactSignedWaiver:
    """Answers: "What exact waiver did this student sign?"

    Returns the signature row, the referenced template version, the captured
    artifact pointer, and a hash-match flag.
    """

    def __init__(
        self,
        signatures: WaiverSignatureRepository,
        templates: WaiverTemplateRepository,
    ) -> None:
        self._signatures = signatures
        self._templates = templates

    async def execute(self, student_id: str) -> ExactSignedWaiver:
        signature = await self._signatures.latest_for_student(student_id)
        if signature is None:
            raise SignedWaiverNotFound(
                f"No waiver signature on file for student {student_id!r}"
            )
        template = await self._templates.get(signature.waiver_template_id)
        if template is None:
            raise SignedWaiverNotFound(
                f"Signature {signature.waiver_signature_id!r} references "
                f"missing template {signature.waiver_template_id!r}"
            )
        return ExactSignedWaiver(
            signature=signature,
            template=template,
            artifact_id=signature.artifact_id,
            signature_matches_template=(
                bool(signature.content_hash)
                and signature.content_hash == template.content_hash
            ),
        )
