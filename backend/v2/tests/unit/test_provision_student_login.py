"""Unit tests for the ProvisionStudentLogin use case (UIM12)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.provision_student_login import (
    ProvisionStudentLogin,
    ProvisionStudentLoginCommand,
)
from backend.v2.contexts.identity.domain.errors import StudentAlreadyLinked


class _FakeProvisioner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.linked: set[str] = set()

    async def ensure_student_login(
        self,
        *,
        student_id: str,
        email: str,
        display_name: str,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> str:
        self.calls.append(
            {
                "student_id": student_id,
                "email": email,
                "display_name": display_name,
                "academy_id": academy_id,
                "actor_id": actor_id,
                "reason": reason,
            }
        )
        if student_id in self.linked:
            raise StudentAlreadyLinked(f"student {student_id} already linked")
        self.linked.add(student_id)
        return f"user-{student_id}"


def _command(**overrides: object) -> ProvisionStudentLoginCommand:
    base = {
        "student_id": "st-1",
        "email": "student@example.com",
        "display_name": "Alex Chen",
        "actor_id": "admin-1",
    }
    base.update(overrides)
    return ProvisionStudentLoginCommand(**base)  # type: ignore[arg-type]


async def test_execute_delegates_to_provisioner_and_returns_user_id() -> None:
    provisioner = _FakeProvisioner()
    use_case = ProvisionStudentLogin(provisioner)

    user_id = await use_case.execute(_command(), academy_id="acad-1")

    assert user_id == "user-st-1"
    assert provisioner.calls == [
        {
            "student_id": "st-1",
            "email": "student@example.com",
            "display_name": "Alex Chen",
            "academy_id": "acad-1",
            "actor_id": "admin-1",
            "reason": "student login invite",
        }
    ]


async def test_execute_forwards_the_admin_supplied_reason_for_the_audit_row() -> None:
    provisioner = _FakeProvisioner()
    use_case = ProvisionStudentLogin(provisioner)

    await use_case.execute(
        _command(reason="parent asked for teen portal access"), academy_id="acad-1"
    )

    assert provisioner.calls[0]["reason"] == "parent asked for teen portal access"


async def test_execute_second_invite_for_same_student_raises_already_linked() -> None:
    """Invite idempotency: a second invite for an already-linked student is
    rejected cleanly rather than silently re-linking or creating a second
    login."""
    provisioner = _FakeProvisioner()
    use_case = ProvisionStudentLogin(provisioner)
    await use_case.execute(_command(), academy_id="acad-1")

    with pytest.raises(StudentAlreadyLinked):
        await use_case.execute(_command(), academy_id="acad-1")
