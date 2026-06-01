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
    signed_at: datetime | None = None


class ParentWaiverStudentStatus(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str
    status: ParentWaiverStatus
    signed_at: datetime | None = None
    waiver_version: str | None = None


class ParentWaiverRequirement(BaseModel):
    model_config = {"frozen": True}

    required: bool
    waiver_template_id: str | None = None
    title: str | None = None
    version: str | None = None
    body: str | None = None
    students: list[ParentWaiverStudentStatus]


class ParentWaiverRepository(Protocol):
    async def get_required_template(self) -> AdminWaiverTemplateRecord | None: ...
    async def list_active_students_for_parent(
        self, parent_id: str
    ) -> list[ParentWaiverStudent]: ...
    async def latest_signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[str, ParentWaiverSignature]: ...
    async def save_signature(self, signature: WaiverSignature) -> None: ...


class GetParentWaiverRequirement:
    def __init__(self, *, waivers: ParentWaiverRepository) -> None:
        self._waivers = waivers

    async def execute(self, *, parent_id: str) -> ParentWaiverRequirement:
        template = await self._waivers.get_required_template()
        students = await self._waivers.list_active_students_for_parent(parent_id)
        if template is None:
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
        signatures = await self._waivers.latest_signatures_for_students(
            [student.student_id for student in students]
        )
        return _requirement_view(template, students, signatures)


class AcceptParentWaiver:
    def __init__(
        self,
        *,
        waivers: ParentWaiverRepository,
        academy_id: str,
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
        template = await self._waivers.get_required_template()
        students = await self._waivers.list_active_students_for_parent(parent_id)
        if template is None:
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

        signatures = await self._waivers.latest_signatures_for_students(
            [student.student_id for student in students]
        )
        now = self._clock()
        for student in students:
            existing = signatures.get(student.student_id)
            if existing and _is_current(existing, template):
                continue
            signature = WaiverSignature(
                waiver_signature_id=self._id_factory(),
                academy_id=self._academy_id,
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

        signatures = await self._waivers.latest_signatures_for_students(
            [student.student_id for student in students]
        )
        return _requirement_view(template, students, signatures)


def _requirement_view(
    template: AdminWaiverTemplateRecord,
    students: list[ParentWaiverStudent],
    signatures: dict[str, ParentWaiverSignature],
) -> ParentWaiverRequirement:
    return ParentWaiverRequirement(
        required=True,
        waiver_template_id=template.waiver_template_id,
        title=template.title,
        version=template.version,
        body=template.body,
        students=[
            _student_status(student, template, signatures.get(student.student_id))
            for student in students
        ],
    )


def _student_status(
    student: ParentWaiverStudent,
    template: AdminWaiverTemplateRecord,
    signature: ParentWaiverSignature | None,
) -> ParentWaiverStudentStatus:
    if signature is None:
        status: ParentWaiverStatus = "pending"
    elif _is_current(signature, template):
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


def _is_current(
    signature: ParentWaiverSignature,
    template: AdminWaiverTemplateRecord,
) -> bool:
    if signature.content_hash and template.content_hash:
        return signature.content_hash == template.content_hash
    if signature.waiver_template_id and signature.waiver_template_id == template.waiver_template_id:
        return True
    return bool(signature.waiver_version and signature.waiver_version == template.version)
