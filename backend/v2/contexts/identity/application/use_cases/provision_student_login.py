"""Provision a Firebase-backed login for a roster student (UIM12).

Mirrors `provision_parent_login`: an admin supplies an email for an existing
student, this use case creates/reuses a Firebase user, grants a `student`
`AcademyMembership`, and links the student roster record to that user via
`Student.student_user_id`. The admin route then reuses the existing
`SendLoginInvite` machinery unchanged (same "set your password" email as
parents get) — this use case only provisions the account, it never sends
mail itself.

"One user per student per academy" is enforced by the port implementation
(`_StudentLoginProvisionerAdapter` in `composition/admin.py`), which raises
`StudentAlreadyLinked` when the student already has a `student_user_id`.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from backend.v2.contexts.identity.application.ports import StudentLoginProvisioner


class ProvisionStudentLoginCommand(BaseModel):
    model_config = {"frozen": True}

    student_id: str = Field(min_length=1, max_length=128)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=128)
    # Recorded on the `student.login_provisioned` audit row, the same way
    # the sibling admin user-management routes record theirs. Granting a
    # login is a privilege change; "who did it and why" belongs in the
    # audit trail, not just in the request body.
    reason: str = Field(default="student login invite", min_length=1, max_length=500)


class ProvisionStudentLogin:
    def __init__(self, students: StudentLoginProvisioner) -> None:
        self._students = students

    async def execute(self, command: ProvisionStudentLoginCommand, *, academy_id: str) -> str:
        return await self._students.ensure_student_login(
            student_id=command.student_id,
            email=str(command.email),
            display_name=command.display_name,
            academy_id=academy_id,
            actor_id=command.actor_id,
            reason=command.reason,
        )
