"""Admin waiver read model use case.

Reports only signals that can be derived from stored waiver documents,
acceptances, students, and parent users. Expiry/renewal policy is intentionally
omitted because the current collections do not store a validity rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.onboarding.domain.waiver_assignment import (
    LEGACY_LINEAGE_KEY,
    WaiverAssignment,
    WaiverScope,
)

WaiverStatus = Literal["current", "signed", "pending", "outdated"]


class AdminWaiverDocument(BaseModel):
    model_config = {"frozen": True}

    waiver_id: str
    version: str
    title: str | None = None
    body: str | None = None
    content_hash: str | None = None
    effective_from: datetime | None = None
    # Which waiver (across versions) this is, and who must sign it. The
    # defaults read as "the one waiver every family signs" so callers that
    # only know a single waiver keep their old meaning.
    lineage_key: str = LEGACY_LINEAGE_KEY
    required: bool = True
    scope: WaiverScope = "all"
    program_ids: list[str] = Field(default_factory=list)

    @property
    def assignment(self) -> WaiverAssignment:
        return WaiverAssignment(
            required=self.required,
            scope=self.scope,
            program_ids=tuple(self.program_ids),
        )


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
    share_link_id: str | None = None


class AdminWaiverData(BaseModel):
    model_config = {"frozen": True}

    active_waiver: AdminWaiverDocument | None = None
    students: list[AdminWaiverStudent]
    # Latest acceptance per student whatever waiver it was for. Only read when
    # the data carries no per-waiver information (one waiver, or none).
    acceptances_by_student: dict[str, AdminWaiverAcceptance] = Field(default_factory=dict)
    # Every live waiver, one row per lineage (the current version of each),
    # whether or not anyone is required to sign it yet.
    live_waivers: list[AdminWaiverDocument] = Field(default_factory=list)
    # Latest acceptance per (student id, lineage key). ``None``: not supplied.
    acceptances_by_lineage: dict[tuple[str, str], AdminWaiverAcceptance] | None = None
    # Program ids of each student's live classes (for program-scoped waivers).
    program_ids_by_student: dict[str, set[str]] = Field(default_factory=dict)


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
    lineage_key: str | None = None
    waiver_template_id: str | None = None
    waiver_version: str | None = None
    current_waiver_version: str | None = None
    content_hash: str | None = None
    signed_at: datetime | None = None
    signed_by_user_id: str | None = None
    artifact_status: str = "unavailable"
    share_status: str = "unavailable"


class AdminWaiverLineageReport(BaseModel):
    """One live waiver: who it applies to and where each of them stands."""

    model_config = {"frozen": True}

    waiver: AdminWaiverDocument
    summary: AdminWaiverSummary
    rows: list[AdminWaiverStudentRow]


class AdminWaiverReport(BaseModel):
    """The waiver report.

    ``summary``, ``active_waiver`` and ``rows`` are the *primary* waiver's (the
    first entry of ``lineages``): a single-waiver academy reads exactly as it
    always did. ``lineages`` carries every live waiver.
    """

    model_config = {"frozen": True}

    summary: AdminWaiverSummary
    active_waiver: AdminWaiverDocument | None = None
    rows: list[AdminWaiverStudentRow]
    lineages: list[AdminWaiverLineageReport] = Field(default_factory=list)
    # Every live waiver (any lineage), required or not: the setup checklist
    # counts "has a live waiver", not "has a required one".
    live_waivers: list[AdminWaiverDocument] = Field(default_factory=list)


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
    artifact_id: str | None = None
    share_link_id: str | None = None
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
        live = list(data.live_waivers)
        if not live and data.active_waiver is not None:
            # A caller that only knows one waiver: it applies to everyone.
            live = [data.active_waiver]
        if not live:
            summary, rows = self._classify(data, None, data.students)
            return AdminWaiverReport(summary=summary, rows=rows)

        # All-family waivers first, so the primary one is the waiver a
        # single-waiver academy has always shown.
        live.sort(key=lambda doc: 0 if doc.assignment.for_all_families else 1)
        lineages: list[AdminWaiverLineageReport] = []
        for doc in live:
            students = [
                student
                for student in data.students
                if doc.assignment.applies_to(
                    data.program_ids_by_student.get(student.student_id, ())
                )
            ]
            summary, rows = self._classify(data, doc, students)
            lineages.append(AdminWaiverLineageReport(waiver=doc, summary=summary, rows=rows))
        primary = lineages[0]
        return AdminWaiverReport(
            summary=primary.summary,
            active_waiver=primary.waiver,
            rows=primary.rows,
            lineages=lineages,
            live_waivers=live,
        )

    def _classify(
        self,
        data: AdminWaiverData,
        waiver: AdminWaiverDocument | None,
        students: list[AdminWaiverStudent],
    ) -> tuple[AdminWaiverSummary, list[AdminWaiverStudentRow]]:
        rows: list[AdminWaiverStudentRow] = []
        signed_count = 0
        current_count = 0
        pending_count = 0
        outdated_count = 0

        for student in students:
            acceptance = self._acceptance_for(data, student.student_id, waiver)
            if acceptance is None:
                status: WaiverStatus = "pending"
                pending_count += 1
            elif self._is_current(acceptance, waiver):
                status = "current"
                signed_count += 1
                current_count += 1
            elif waiver is None:
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
                    lineage_key=waiver.lineage_key if waiver else None,
                    signature_id=acceptance.signature_id if acceptance else None,
                    waiver_template_id=acceptance.waiver_template_id if acceptance else None,
                    waiver_version=acceptance.waiver_version if acceptance else None,
                    current_waiver_version=waiver.version if waiver else None,
                    content_hash=acceptance.content_hash if acceptance else None,
                    signed_at=acceptance.accepted_at if acceptance else None,
                    signed_by_user_id=(acceptance.accepted_by_user_id if acceptance else None),
                    artifact_status=(
                        "stored_reference"
                        if acceptance and acceptance.artifact_id
                        else "unavailable"
                    ),
                    share_status=(
                        "available" if acceptance and acceptance.share_link_id else "unavailable"
                    ),
                )
            )

        return (
            AdminWaiverSummary(
                total_students=len(students),
                signed_count=signed_count,
                current_count=current_count,
                pending_count=pending_count,
                outdated_count=outdated_count,
            ),
            rows,
        )

    @staticmethod
    def _acceptance_for(
        data: AdminWaiverData,
        student_id: str,
        waiver: AdminWaiverDocument | None,
    ) -> AdminWaiverAcceptance | None:
        if data.acceptances_by_lineage is not None and waiver is not None:
            return data.acceptances_by_lineage.get((student_id, waiver.lineage_key))
        return data.acceptances_by_student.get(student_id)

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
