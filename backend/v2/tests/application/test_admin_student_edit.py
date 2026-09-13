"""Admin student detail/edit use-case tests."""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentDetail,
    AdminStudentParentChangeResult,
    AdminStudentParentSummary,
    AdminStudentSessionSummary,
    ChangeAdminStudentParent,
    ChangeAdminStudentParentCommand,
    GetAdminStudent,
    UpdateAdminStudent,
    UpdateAdminStudentCommand,
)
from backend.v2.contexts.enrollment.domain.errors import StudentNotFound


class FakeStudentEditor:
    def __init__(self) -> None:
        self.student = AdminStudentDetail(
            student_id="st-1",
            full_name="Alice Chen",
            parent_id="parent-1",
            parent_name="Parent One",
            parent_email="parent@example.com",
            parent_phone="555-0101",
            lifecycle="active",
            active_session_count=1,
            attendance_rate=None,
            dues_status="current",
            level="beginner",
            previous_experience="Played recreationally",
            medical_notes="Uses inhaler before intense sessions",
            emergency_contact_name="Anita Chen",
            emergency_contact_phone="555-0199",
            t_shirt_size="M",
            waiver_status="signed",
            waiver_signed_at=None,
            waiver_version="2026-v1",
            recent_attendance=[],
        )
        self.commands: list[UpdateAdminStudentCommand] = []
        self.parent_change_commands: list[ChangeAdminStudentParentCommand] = []

    async def get_admin_student(self, student_id: str) -> AdminStudentDetail | None:
        return self.student if student_id == self.student.student_id else None

    async def update_admin_student(
        self,
        student_id: str,
        command: UpdateAdminStudentCommand,
    ) -> AdminStudentDetail | None:
        self.commands.append(command)
        if student_id != self.student.student_id:
            return None
        self.student = self.student.model_copy(
            update={
                "full_name": command.full_name or self.student.full_name,
                "date_of_birth": command.date_of_birth,
                "notes": command.notes,
                "previous_experience": command.previous_experience,
                "medical_notes": command.medical_notes,
                "emergency_contact_name": command.emergency_contact_name,
                "emergency_contact_phone": command.emergency_contact_phone,
                "t_shirt_size": command.t_shirt_size,
            }
        )
        return self.student

    async def change_admin_student_parent(
        self,
        student_id: str,
        command: ChangeAdminStudentParentCommand,
    ) -> AdminStudentParentChangeResult | None:
        self.parent_change_commands.append(command)
        if student_id != self.student.student_id:
            return None
        return AdminStudentParentChangeResult(
            student_id=student_id,
            parent=AdminStudentParentSummary(
                parent_id=command.parent_id,
                display_name="Parent Two",
                email="parent2@example.com",
                phone="555-0202",
            ),
            previous_parent_id=self.student.parent_id,
            warnings=["Historical billing, waiver, credit, and waitlist rows were not rewritten."],
            impact_counts={
                "payments": 1,
                "waivers": 1,
                "credits": 1,
                "waitlist": 1,
            },
        )


@pytest.mark.asyncio
async def test_get_admin_student_returns_parent_contact_details() -> None:
    repo = FakeStudentEditor()

    result = await GetAdminStudent(repo).execute("st-1")

    assert result.parent_email == "parent@example.com"
    assert result.parent_phone == "555-0101"
    assert result.level == "beginner"
    assert result.previous_experience == "Played recreationally"
    assert result.medical_notes == "Uses inhaler before intense sessions"
    assert result.emergency_contact_name == "Anita Chen"
    assert result.emergency_contact_phone == "555-0199"
    assert result.t_shirt_size == "M"
    assert result.waiver_status == "signed"
    assert result.waiver_version == "2026-v1"


class FakeAutopayLookup:
    def __init__(self, statuses: dict[str, str | None]) -> None:
        self.statuses = statuses
        self.calls: list[list[str]] = []

    async def autopay_status_by_enrollment(
        self, enrollment_ids: list[str]
    ) -> dict[str, str | None]:
        self.calls.append(list(enrollment_ids))
        return {k: v for k, v in self.statuses.items() if k in enrollment_ids}


def _session(enrollment_id: str, status: str = "active") -> AdminStudentSessionSummary:
    return AdminStudentSessionSummary(
        enrollment_id=enrollment_id,
        session_id=f"sess-{enrollment_id}",
        session_title="Advanced Footwork",
        status=status,
    )


@pytest.mark.asyncio
async def test_get_admin_student_enriches_current_rows_with_autopay_status() -> None:
    """Issue #674: autopay comes from billing through the port; current rows
    get it, past rows are left alone, and an unknown id stays None."""
    repo = FakeStudentEditor()
    repo.student = repo.student.model_copy(
        update={
            "enrolled_sessions": [_session("enr-on"), _session("enr-unknown", status="paused")],
            "past_enrollments": [_session("enr-old", status="cancelled")],
        }
    )
    autopay = FakeAutopayLookup({"enr-on": "active", "enr-old": "disabled"})

    result = await GetAdminStudent(repo, autopay=autopay).execute("st-1")

    assert autopay.calls == [["enr-on", "enr-unknown"]]
    assert [(r.enrollment_id, r.autopay_status) for r in result.enrolled_sessions] == [
        ("enr-on", "active"),
        ("enr-unknown", None),
    ]
    assert result.past_enrollments[0].autopay_status is None
    # Everything else on the detail is untouched by the enrichment copy.
    assert result.parent_email == "parent@example.com"


@pytest.mark.asyncio
async def test_get_admin_student_without_autopay_port_keeps_rows_unchanged() -> None:
    repo = FakeStudentEditor()
    repo.student = repo.student.model_copy(update={"enrolled_sessions": [_session("enr-on")]})

    result = await GetAdminStudent(repo).execute("st-1")

    assert result.enrolled_sessions[0].autopay_status is None


@pytest.mark.asyncio
async def test_update_admin_student_forwards_safe_fields_with_audit_context() -> None:
    repo = FakeStudentEditor()
    command = UpdateAdminStudentCommand(
        full_name="Alice Rao",
        date_of_birth=date(2016, 4, 5),
        notes="Prefers evening classes",
        previous_experience="Tournament prep",
        medical_notes="No restrictions",
        emergency_contact_name="Rina Rao",
        emergency_contact_phone="555-0303",
        t_shirt_size="L",
        actor_id="admin-1",
        reason="Parent requested profile correction",
    )

    result = await UpdateAdminStudent(repo).execute("st-1", command)

    assert result.full_name == "Alice Rao"
    assert result.date_of_birth == date(2016, 4, 5)
    assert result.previous_experience == "Tournament prep"
    assert result.medical_notes == "No restrictions"
    assert result.emergency_contact_name == "Rina Rao"
    assert result.emergency_contact_phone == "555-0303"
    assert result.t_shirt_size == "L"
    assert repo.commands == [command]


@pytest.mark.asyncio
async def test_update_admin_student_raises_when_missing() -> None:
    repo = FakeStudentEditor()

    with pytest.raises(StudentNotFound):
        await UpdateAdminStudent(repo).execute(
            "missing",
            UpdateAdminStudentCommand(
                full_name="Missing",
                actor_id="admin-1",
                reason="correction",
            ),
        )


@pytest.mark.asyncio
async def test_change_admin_student_parent_forwards_parent_and_audit_context() -> None:
    repo = FakeStudentEditor()
    command = ChangeAdminStudentParentCommand(
        parent_id="parent-2",
        actor_id="admin-1",
        reason="Custody update",
    )

    result = await ChangeAdminStudentParent(repo).execute("st-1", command)

    assert result.student_id == "st-1"
    assert result.parent.parent_id == "parent-2"
    assert result.previous_parent_id == "parent-1"
    assert result.impact_counts["payments"] == 1
    assert repo.parent_change_commands == [command]


@pytest.mark.asyncio
async def test_change_admin_student_parent_raises_when_student_missing() -> None:
    repo = FakeStudentEditor()

    with pytest.raises(StudentNotFound):
        await ChangeAdminStudentParent(repo).execute(
            "missing",
            ChangeAdminStudentParentCommand(
                parent_id="parent-2",
                actor_id="admin-1",
                reason="Custody update",
            ),
        )
