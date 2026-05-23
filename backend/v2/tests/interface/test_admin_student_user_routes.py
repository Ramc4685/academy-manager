"""Admin student/user detail and edit BFF routes."""

from __future__ import annotations

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentDetail,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
    AdminUserSummary,
)


class StudentDetailStub:
    def __init__(self) -> None:
        self.updated = None

    async def execute(self, student_id, command=None):
        if command is not None:
            self.updated = command
            return AdminStudentDetail(
                student_id=student_id,
                full_name=command.full_name or "Alice Chen",
                parent_id="parent-1",
                parent_name="Parent One",
                parent_email="parent@example.com",
                parent_phone="555-0101",
                status=command.status or "active",
                active_session_count=1,
                attendance_rate=None,
                dues_status="current",
                level=command.level,
                notes=command.notes,
            )
        return AdminStudentDetail(
            student_id=student_id,
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
            notes="Bring water",
        )


class UserDetailStub:
    def __init__(self) -> None:
        self.updated = None

    async def execute(self, user_id, command=None, *, academy_id):
        _ = academy_id
        if command is not None:
            self.updated = command
            return AdminUserDetail(
                user_id=user_id,
                email="parent@example.com",
                display_name=command.display_name or "Parent One",
                phone=command.phone,
                role="parent",
                roles=("parent",),
                status=command.status or "active",
                linked_student_count=1,
            )
        return AdminUserDetail(
            user_id=user_id,
            email="parent@example.com",
            display_name="Parent One",
            phone="555-0101",
            role="parent",
            roles=("parent",),
            status="active",
            linked_student_count=1,
        )


class RoleChangeStub:
    def __init__(self) -> None:
        self.command = None

    async def execute(self, user_id, command, *, academy_id):
        _ = academy_id
        self.command = command
        return AdminUserSummary(
            user_id=user_id,
            email="coach@example.com",
            display_name="Coach One",
            phone="555-0102",
            role=command.role,
            status="active",
        )


def test_admin_can_get_and_update_student_detail(admin_client):
    stub = StudentDetailStub()
    admin_client.use_cases.get_admin_student = stub  # type: ignore[attr-defined]
    admin_client.use_cases.update_admin_student = stub  # type: ignore[attr-defined]

    detail = admin_client.get("/api/v2/admin/students/st-1")
    assert detail.status_code == 200, detail.text
    assert detail.json()["parent_phone"] == "555-0101"

    updated = admin_client.patch(
        "/api/v2/admin/students/st-1",
        json={
            "full_name": "Alice Rao",
            "level": "intermediate",
            "status": "paused",
            "notes": "Prefers evenings",
            "reason": "Parent requested correction",
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Alice Rao"
    assert stub.updated.actor_id == "u-admin"
    assert stub.updated.reason == "Parent requested correction"


def test_admin_can_get_and_update_user_detail(admin_client):
    stub = UserDetailStub()
    admin_client.use_cases.get_admin_user = stub  # type: ignore[attr-defined]
    admin_client.use_cases.update_admin_user = stub  # type: ignore[attr-defined]

    detail = admin_client.get("/api/v2/admin/users/user-1")
    assert detail.status_code == 200, detail.text
    assert detail.json()["phone"] == "555-0101"
    assert detail.json()["linked_student_count"] == 1

    updated = admin_client.patch(
        "/api/v2/admin/users/user-1",
        json={
            "display_name": "Parent Updated",
            "phone": "555-0199",
            "status": "inactive",
            "reason": "Parent requested correction",
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Parent Updated"
    assert stub.updated.actor_id == "u-admin"
    assert stub.updated.reason == "Parent requested correction"


def test_role_change_uses_explicit_audit_context(admin_client):
    stub = RoleChangeStub()
    admin_client.use_cases.change_user_role = stub  # type: ignore[attr-defined]

    response = admin_client.patch(
        "/api/v2/admin/users/user-1/role",
        json={"role": "coach", "reason": "Coach onboarding"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "coach"
    assert stub.command.actor_id == "u-admin"
    assert stub.command.reason == "Coach onboarding"


def test_user_and_student_detail_wrong_persona_404(coach_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/users/user-1").status_code == 404
    assert coach_on_admin_client.get("/api/v2/admin/students/st-1").status_code == 404
