"""Per-waiver signing status for one student (admin student page).

One row per live waiver that applies to the student through their classes:
required for all families, or assigned to a program one of their live classes
sits in. Each row says whether the student has signed it: the live version, an
older version, or not at all.

"Signed" follows the parent waiver rule (``signature_is_current``): an older
version's signature still counts when its content hash matches the live one. A
missing signature is a WARNING for staff, never a block (owner decision 9).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    ParentWaiverSignature,
    signature_is_current,
)

StudentWaiverState = Literal["signed", "older_version", "unsigned"]


class StudentWaiverStatusReader(Protocol):
    async def list_required_templates(self) -> list[AdminWaiverTemplateRecord]: ...
    async def program_ids_for_students(self, student_ids: list[str]) -> dict[str, set[str]]: ...
    async def signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[tuple[str, str], ParentWaiverSignature]: ...
    async def legacy_flag_signatures(
        self, student_ids: list[str]
    ) -> dict[tuple[str, str], ParentWaiverSignature]:
        """Signatures implied by the old ``students.waiver_accepted`` flag.

        Keyed by (student id, legacy lineage). Staff compliance views count the
        flag as a signature, so this status must too.
        """
        ...


class StudentWaiverRow(BaseModel):
    model_config = {"frozen": True}

    waiver_template_id: str
    lineage_key: str
    title: str
    version: str | None = None
    status: StudentWaiverState
    signed_version: str | None = None
    signed_at: datetime | None = None
    signature_id: str | None = None


class StudentWaiverStatus(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    waivers: list[StudentWaiverRow]

    @property
    def unsigned(self) -> list[StudentWaiverRow]:
        return [row for row in self.waivers if row.status != "signed"]


class GetStudentWaiverStatus:
    def __init__(self, reader: StudentWaiverStatusReader) -> None:
        self._reader = reader

    async def execute(self, student_id: str) -> StudentWaiverStatus:
        templates = await self._reader.list_required_templates()
        if not templates:
            return StudentWaiverStatus(student_id=student_id, waivers=[])
        programs = (await self._reader.program_ids_for_students([student_id])).get(
            student_id, set()
        )
        applicable = [t for t in templates if t.assignment.applies_to(programs)]
        applicable.sort(key=lambda t: 0 if t.assignment.for_all_families else 1)
        signatures = dict(await self._reader.signatures_for_students([student_id]))
        # Fallback only: a real signature row always wins over the old flag.
        for key, flagged in (await self._reader.legacy_flag_signatures([student_id])).items():
            signatures.setdefault(key, flagged)
        rows: list[StudentWaiverRow] = []
        for template in applicable:
            signature = signatures.get((student_id, template.lineage))
            if signature is None:
                state: StudentWaiverState = "unsigned"
            elif _is_bare_legacy_flag(signature) or signature_is_current(signature, template):
                state = "signed"
            else:
                state = "older_version"
            rows.append(
                StudentWaiverRow(
                    waiver_template_id=template.waiver_template_id,
                    lineage_key=template.lineage,
                    title=template.title,
                    version=template.version,
                    status=state,
                    signed_version=(signature.signed_version or signature.waiver_version)
                    if signature
                    else None,
                    signed_at=signature.signed_at if signature else None,
                    signature_id=signature.waiver_signature_id if signature else None,
                )
            )
        return StudentWaiverStatus(student_id=student_id, waivers=rows)


def _is_bare_legacy_flag(signature: ParentWaiverSignature) -> bool:
    """A flag-only acceptance that names no template, hash or version.

    Nothing to compare against the live wording, so it reads as signed, the way
    the admin compliance summary already counts it.
    """
    return not (signature.waiver_template_id or signature.content_hash or signature.waiver_version)
