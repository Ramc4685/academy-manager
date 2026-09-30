"""Parent-facing required waiver read/sign use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.domain.models import WaiverSignature
from backend.v2.contexts.onboarding.domain.waiver_assignment import LEGACY_LINEAGE_KEY
from backend.v2.shared.ids import new_ulid

ParentWaiverStatus = Literal["signed", "pending", "outdated", "not_required"]


class ParentWaiverStudent(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str


class ParentWaiverSignature(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    waiver_template_id: str | None = None
    waiver_version: str | None = None
    content_hash: str | None = None
    # Who signed. A child whose guardian changed keeps the old parent's
    # signature row, and keying only by student made the new parent's page read
    # "signed" off a stranger's consent (#785). ``None`` means the stored row
    # predates the field: treated as "signer unknown", never as a mismatch.
    parent_user_id: str | None = None
    # Stamped by the admin change-parent write. Belt and braces for rows whose
    # ``parent_user_id`` is unknown but which we know were inherited.
    outdated_for_parent: bool = False
    signed_at: datetime | None = None
    # Which waiver (across versions) the signature is for; ``None`` reads as the
    # legacy lineage, and so does a signature whose template has no key.
    lineage_key: str | None = None
    waiver_signature_id: str | None = None
    # The version of the template the signature pins to (for staff views).
    signed_version: str | None = None

    @property
    def lineage(self) -> str:
        return self.lineage_key or LEGACY_LINEAGE_KEY


class ParentWaiverStudentStatus(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str
    status: ParentWaiverStatus
    signed_at: datetime | None = None
    waiver_version: str | None = None


class ParentWaiverItem(BaseModel):
    """One waiver and the children who must sign it."""

    model_config = {"frozen": True}

    waiver_template_id: str
    title: str | None = None
    version: str | None = None
    body: str | None = None
    students: list[ParentWaiverStudentStatus]


class ParentWaiverRequirement(BaseModel):
    model_config = {"frozen": True}

    required: bool
    # The first waiver, flat: a single-waiver academy (every academy today)
    # reads exactly as it always has.
    waiver_template_id: str | None = None
    title: str | None = None
    version: str | None = None
    body: str | None = None
    students: list[ParentWaiverStudentStatus]
    waivers: list[ParentWaiverItem] = []


class ParentWaiverRepository(Protocol):
    async def list_required_templates(self) -> list[AdminWaiverTemplateRecord]: ...
    async def list_active_students_for_parent(
        self, parent_id: str
    ) -> list[ParentWaiverStudent]: ...
    async def program_ids_for_students(self, student_ids: list[str]) -> dict[str, set[str]]: ...
    async def signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[tuple[str, str], ParentWaiverSignature]:
        """Latest signature per (student id, lineage key)."""
        ...

    async def save_signature(self, signature: WaiverSignature) -> None: ...


class _RequiredSet(BaseModel):
    """The live waivers that apply to this parent's children, and to whom."""

    model_config = {"frozen": True}

    students: list[ParentWaiverStudent]
    # (template, students it applies to), in display order.
    waivers: list[tuple[AdminWaiverTemplateRecord, list[ParentWaiverStudent]]]


async def _required_set(waivers: ParentWaiverRepository, parent_id: str) -> _RequiredSet:
    templates = await waivers.list_required_templates()
    students = await waivers.list_active_students_for_parent(parent_id)
    if not templates:
        return _RequiredSet(students=students, waivers=[])
    if not students:
        # No live-enrolled child: the page still shows the waiver everyone
        # signs (as it did with one registration waiver), with nobody to sign.
        everyone = [t for t in templates if t.assignment.for_all_families]
        return _RequiredSet(students=students, waivers=[(t, []) for t in everyone])
    programs = await waivers.program_ids_for_students([s.student_id for s in students])
    applicable: list[tuple[AdminWaiverTemplateRecord, list[ParentWaiverStudent]]] = []
    for template in templates:
        covered = [
            student
            for student in students
            if template.assignment.applies_to(programs.get(student.student_id, set()))
        ]
        if covered:
            applicable.append((template, covered))
    # All-family waivers first: the primary one is the same waiver a
    # single-waiver academy has always shown.
    applicable.sort(key=lambda pair: 0 if pair[0].assignment.for_all_families else 1)
    return _RequiredSet(students=students, waivers=applicable)


def _not_required(students: list[ParentWaiverStudent]) -> ParentWaiverRequirement:
    return ParentWaiverRequirement(
        required=False,
        students=[
            ParentWaiverStudentStatus(
                student_id=student.student_id,
                student_name=student.student_name,
                status="not_required",
            )
            for student in students
        ],
    )


class GetParentWaiverRequirement:
    def __init__(self, *, waivers: ParentWaiverRepository) -> None:
        self._waivers = waivers

    async def execute(self, *, parent_id: str) -> ParentWaiverRequirement:
        required = await _required_set(self._waivers, parent_id)
        if not required.waivers:
            return _not_required(required.students)
        signatures = await self._waivers.signatures_for_students(
            [student.student_id for student in required.students]
        )
        return _requirement_view(required, signatures, parent_id=parent_id)


class AcceptParentWaiver:
    def __init__(
        self,
        *,
        waivers: ParentWaiverRepository,
        academy_id: Callable[[], str],
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._waivers = waivers
        self._academy_id = academy_id
        self._id_factory = id_factory or (lambda: f"ws_{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        parent_id: str,
        signer_name: str | None,
        signer_email: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ParentWaiverRequirement:
        required = await _required_set(self._waivers, parent_id)
        if not required.waivers:
            return _not_required(required.students)

        signatures = await self._waivers.signatures_for_students(
            [student.student_id for student in required.students]
        )
        now = self._clock()
        # Request-time tenant via the injected provider — never a boot-time value.
        academy_id = self._academy_id()
        for template, covered in required.waivers:
            for student in covered:
                existing = signatures.get((student.student_id, template.lineage))
                if existing and _is_current(existing, template) and _signed_by(existing, parent_id):
                    continue
                signature = WaiverSignature(
                    waiver_signature_id=self._id_factory(),
                    academy_id=academy_id,
                    waiver_template_id=template.waiver_template_id,
                    student_id=student.student_id,
                    parent_user_id=parent_id,
                    signed_at=now,
                    signer_name=signer_name or signer_email,
                    signer_email=signer_email,
                    content_hash=template.content_hash or "",
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                await self._waivers.save_signature(signature)

        signatures = await self._waivers.signatures_for_students(
            [student.student_id for student in required.students]
        )
        return _requirement_view(required, signatures, parent_id=parent_id)


def _requirement_view(
    required: _RequiredSet,
    signatures: dict[tuple[str, str], ParentWaiverSignature],
    *,
    parent_id: str,
) -> ParentWaiverRequirement:
    items = [
        ParentWaiverItem(
            waiver_template_id=template.waiver_template_id,
            title=template.title,
            version=template.version,
            body=template.body,
            students=[
                _student_status(
                    student,
                    template,
                    signatures.get((student.student_id, template.lineage)),
                    parent_id=parent_id,
                )
                for student in covered
            ],
        )
        for template, covered in required.waivers
    ]
    first = items[0]
    return ParentWaiverRequirement(
        required=True,
        waiver_template_id=first.waiver_template_id,
        title=first.title,
        version=first.version,
        body=first.body,
        students=first.students,
        waivers=items,
    )


def _student_status(
    student: ParentWaiverStudent,
    template: AdminWaiverTemplateRecord,
    signature: ParentWaiverSignature | None,
    *,
    parent_id: str,
) -> ParentWaiverStudentStatus:
    if signature is None:
        status: ParentWaiverStatus = "pending"
    elif _is_current(signature, template) and _signed_by(signature, parent_id):
        status = "signed"
    else:
        status = "outdated"
    return ParentWaiverStudentStatus(
        student_id=student.student_id,
        student_name=student.student_name,
        status=status,
        signed_at=signature.signed_at if signature else None,
        waiver_version=signature.waiver_version or template.version if signature else None,
    )


def _signed_by(signature: ParentWaiverSignature, parent_id: str) -> bool:
    """True when this signature is the *requesting* parent's own consent.

    Issue #785: signatures are keyed by student, so an admin moving a child to
    a new guardian left the new parent's page reading "signed" off the previous
    parent's consent — and `AcceptParentWaiver` skipped the child, so the
    academy held no waiver from the person who now has custody.

    A row with no recorded signer predates the field and is left alone: a
    blanket re-sign prompt for every legacy family is worse than the gap.
    """
    if signature.outdated_for_parent:
        return False
    if signature.parent_user_id is None:
        return True
    return signature.parent_user_id == parent_id


def signature_is_current(
    signature: ParentWaiverSignature,
    template: AdminWaiverTemplateRecord,
) -> bool:
    """Whether an older-or-equal signature still counts for this live version.

    Same content hash counts; without hashes the same template id or version
    does. A signature for an older version with different wording does not.
    """
    return _is_current(signature, template)


def _is_current(
    signature: ParentWaiverSignature,
    template: AdminWaiverTemplateRecord,
) -> bool:
    if signature.content_hash and template.content_hash:
        return signature.content_hash == template.content_hash
    if signature.waiver_template_id and signature.waiver_template_id == template.waiver_template_id:
        return True
    return bool(signature.waiver_version and signature.waiver_version == template.version)
