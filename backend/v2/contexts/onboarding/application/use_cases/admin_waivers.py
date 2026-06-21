"""Admin waiver read model use case.

Reports only signals that can be derived from stored waiver documents,
acceptances, students, and parent users. Expiry/renewal policy is intentionally
omitted because the current collections do not store a validity rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

WaiverStatus = Literal["current", "signed", "pending", "outdated"]


class AdminWaiverDocument(BaseModel):
    model_config = {"frozen": True}

    waiver_id: str
    version: str
    title: str | None = None
    body: str | None = None
    content_hash: str | None = None
    effective_from: datetime | None = None


class AdminWaiverStudent(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    full_name: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None


class AdminWaiverAcceptance(BaseModel):
    model_config = {"frozen": True}

    signature_id: str | None = None
    student_id: str
    parent_id: str
    accepted_by_user_id: str | None = None
    waiver_template_id: str | None = None
    waiver_version: str | None = None
    content_hash: str | None = None
    accepted_at: datetime | None = None
    signer_name: str | None = None
    signer_email: str | None = None
    artifact_id: str | None = None


class AdminWaiverData(BaseModel):
    model_config = {"frozen": True}

    active_waiver: AdminWaiverDocument | None = None
    students: list[AdminWaiverStudent]
    acceptances_by_student: dict[str, AdminWaiverAcceptance]


class AdminWaiverSummary(BaseModel):
    model_config = {"frozen": True}

    total_students: int
    signed_count: int
    current_count: int
    pending_count: int
    outdated_count: int


class AdminWaiverStudentRow(BaseModel):
    model_config = {"frozen": True}

    signature_id: str | None = None
    student_id: str
    student_name: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    status: WaiverStatus
    waiver_template_id: str | None = None
    waiver_version: str | None = None
    current_waiver_version: str | None = None
    content_hash: str | None = None
    signed_at: datetime | None = None
    signed_by_user_id: str | None = None
    artifact_status: str = "unavailable"
    share_status: str = "unavailable"


class AdminWaiverReport(BaseModel):
    model_config = {"frozen": True}

    summary: AdminWaiverSummary
    active_waiver: AdminWaiverDocument | None = None
    rows: list[AdminWaiverStudentRow]


class AdminWaiverTemplateDetail(BaseModel):
    model_config = {"frozen": True}

    waiver_id: str
    title: str
    version: str
    status: Literal["draft", "active", "superseded", "retired"] = "active"
    body: str | None = None
    content_hash: str | None = None
    effective_from: datetime | None = None
    assigned_to_registration: bool = False
    assigned_at: datetime | None = None
    artifact_status: str = "unavailable"
    share_status: str = "unavailable"
    gap_note: str = "Signed PDF artifact/share links are not implemented yet."


class AdminWaiverSignatureDetail(BaseModel):
    model_config = {"frozen": True}

    signature_id: str
    student_id: str
    student_name: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    signed_at: datetime
    signer_name: str | None = None
    signer_email: str | None = None
    waiver_template_id: str | None = None
    waiver_title: str | None = None
    waiver_version: str | None = None
    content_hash: str | None = None
    artifact_status: str = "unavailable"
    share_status: str = "unavailable"
    gap_note: str = "Signed PDF artifact/share links are not implemented yet."


class AdminWaiverQuery(Protocol):
    async def load_admin_waiver_data(self) -> AdminWaiverData: ...
    async def get_template_detail(self, waiver_id: str) -> AdminWaiverTemplateDetail | None: ...
    async def get_signature_detail(
        self, signature_id: str
    ) -> AdminWaiverSignatureDetail | None: ...


class ListAdminWaivers:
    def __init__(self, waivers: AdminWaiverQuery) -> None:
        self._waivers = waivers

    async def execute(self) -> AdminWaiverReport:
        data = await self._waivers.load_admin_waiver_data()
        rows: list[AdminWaiverStudentRow] = []
        signed_count = 0
        current_count = 0
        pending_count = 0
        outdated_count = 0

        for student in data.students:
            acceptance = data.acceptances_by_student.get(student.student_id)
            if acceptance is None:
                status: WaiverStatus = "pending"
                pending_count += 1
            elif self._is_current(acceptance, data.active_waiver):
                status = "current"
                signed_count += 1
                current_count += 1
            elif data.active_waiver is None:
                status = "signed"
                signed_count += 1
            else:
                status = "outdated"
                signed_count += 1
                outdated_count += 1

            rows.append(
                AdminWaiverStudentRow(
                    student_id=student.student_id,
                    student_name=student.full_name,
                    parent_id=student.parent_id,
                    parent_name=student.parent_name,
                    parent_email=student.parent_email,
                    status=status,
                    signature_id=acceptance.signature_id if acceptance else None,
                    waiver_template_id=acceptance.waiver_template_id if acceptance else None,
                    waiver_version=acceptance.waiver_version if acceptance else None,
                    current_waiver_version=(
                        data.active_waiver.version if data.active_waiver else None
                    ),
                    content_hash=acceptance.content_hash if acceptance else None,
                    signed_at=acceptance.accepted_at if acceptance else None,
                    signed_by_user_id=(acceptance.accepted_by_user_id if acceptance else None),
                    artifact_status=(
                        "stored_reference"
                        if acceptance and acceptance.artifact_id
                        else "unavailable"
                    ),
                    share_status="unavailable",
                )
            )

        return AdminWaiverReport(
            summary=AdminWaiverSummary(
                total_students=len(data.students),
                signed_count=signed_count,
                current_count=current_count,
                pending_count=pending_count,
                outdated_count=outdated_count,
            ),
            active_waiver=data.active_waiver,
            rows=rows,
        )

    @staticmethod
    def _is_current(
        acceptance: AdminWaiverAcceptance,
        active: AdminWaiverDocument | None,
    ) -> bool:
        if active is None:
            return False
        if (
            acceptance.content_hash
            and active.content_hash
            and acceptance.content_hash == active.content_hash
        ):
            return True
        return bool(
            acceptance.waiver_version
            and active.version
            and acceptance.waiver_version == active.version
        )

    async def template_detail(self, waiver_id: str) -> AdminWaiverTemplateDetail | None:
        return await self._waivers.get_template_detail(waiver_id)

    async def signature_detail(self, signature_id: str) -> AdminWaiverSignatureDetail | None:
        return await self._waivers.get_signature_detail(signature_id)
