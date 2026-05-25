"""Admin student detail/edit use-case tests."""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentDetail,
    AdminStudentParentChangeResult,
    AdminStudentParentSummary,
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
            status="active",
            active_session_count=1,
            attendance_rate=None,
            dues_status="current",
            level="beginner",
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
                "level": command.level,
                "status": command.status or self.student.status,
                "notes": command.notes,
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


@pytest.mark.asyncio
async def test_update_admin_student_forwards_safe_fields_with_audit_context() -> None:
    repo = FakeStudentEditor()
    command = UpdateAdminStudentCommand(
        full_name="Alice Rao",
        date_of_birth=date(2016, 4, 5),
        level="intermediate",
        status="paused",
        notes="Prefers evening classes",
        actor_id="admin-1",
        reason="Parent requested profile correction",
    )

    result = await UpdateAdminStudent(repo).execute("st-1", command)

    assert result.full_name == "Alice Rao"
    assert result.date_of_birth == date(2016, 4, 5)
    assert result.status == "paused"
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
