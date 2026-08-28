"""Admin user detail/edit use-case tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.identity.application.change_user_role_use_case import (
    ChangeUserRole,
    ChangeUserRoleCommand,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
    AdminUserSummary,
    GetAdminUser,
    UpdateAdminUser,
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    LoginInviteResult,
)
from backend.v2.contexts.identity.domain.errors import LoginInviteSendFailed, UserNotFound


class FakeUserEditor:
    def __init__(self) -> None:
        self.user = AdminUserDetail(
            user_id="user-1",
            email="parent@example.com",
            display_name="Parent One",
            phone="555-0101",
            role="parent",
            roles=("parent",),
            status="active",
            linked_student_count=2,
        )
        self.update_commands: list[UpdateAdminUserCommand] = []
        self.role_commands: list[dict[str, str]] = []

    async def get_admin_user(self, user_id: str, *, academy_id: str) -> AdminUserDetail | None:
        _ = academy_id
        return self.user if user_id == self.user.user_id else None

    async def update_admin_user(
        self,
        user_id: str,
        command: UpdateAdminUserCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail | None:
        _ = academy_id
        self.update_commands.append(command)
        if user_id != self.user.user_id:
            return None
        self.user = self.user.model_copy(
            update={
                "email": command.email or self.user.email,
                "display_name": command.display_name or self.user.display_name,
                "phone": command.phone,
                "status": command.status or self.user.status,
            }
        )
        return self.user

    async def change_role(
        self,
        user_id: str,
        role: str,
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserSummary | None:
        _ = academy_id
        self.role_commands.append({"actor_id": actor_id, "reason": reason, "role": role})
        if user_id != self.user.user_id:
            return None
        self.user = self.user.model_copy(update={"role": role, "roles": (role,)})
        return AdminUserSummary(**self.user.model_dump())


@pytest.mark.asyncio
async def test_get_admin_user_returns_profile_without_internal_ids() -> None:
    repo = FakeUserEditor()

    result = await GetAdminUser(repo).execute("user-1", academy_id="acad")

    assert result.display_name == "Parent One"
    assert result.phone == "555-0101"
    assert result.linked_student_count == 2


@pytest.mark.asyncio
async def test_update_admin_user_forwards_safe_fields_with_audit_context() -> None:
    repo = FakeUserEditor()
    command = UpdateAdminUserCommand(
        display_name="Parent Updated",
        phone="555-0199",
        status="inactive",
        actor_id="admin-1",
        reason="Parent requested correction",
    )

    result = await UpdateAdminUser(repo).execute("user-1", command, academy_id="acad")

    assert result.user.display_name == "Parent Updated"
    assert result.user.phone == "555-0199"
    assert result.user.status == "inactive"
    assert result.login_invite.status == "not_needed"
    assert repo.update_commands == [command]


@pytest.mark.asyncio
async def test_role_change_requires_explicit_audit_context() -> None:
    repo = FakeUserEditor()

    result = await ChangeUserRole(repo).execute(
        "user-1",
        ChangeUserRoleCommand(
            role="coach",
            actor_id="admin-1",
            reason="Coach onboarding",
        ),
        academy_id="acad",
    )

    assert result.role == "coach"
    assert repo.role_commands == [
        {"actor_id": "admin-1", "reason": "Coach onboarding", "role": "coach"}
    ]


@pytest.mark.asyncio
async def test_update_admin_user_raises_when_missing() -> None:
    repo = FakeUserEditor()

    with pytest.raises(UserNotFound):
        await UpdateAdminUser(repo).execute(
            "missing",
            UpdateAdminUserCommand(actor_id="admin-1", reason="correction"),
            academy_id="acad",
        )


class RecordingInvites:
    """Stands in for `SendLoginInvite` (issue #436)."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_with = fail_with

    async def execute(self, user_id: str, *, academy_id: str) -> LoginInviteResult:
        self.calls.append((user_id, academy_id))
        if self._fail_with is not None:
            raise self._fail_with
        return LoginInviteResult(sent_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC))


def _edit(**kwargs: object) -> UpdateAdminUserCommand:
    return UpdateAdminUserCommand(actor_id="admin-1", reason="typo fix", **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_email_change_sends_exactly_one_login_invite() -> None:
    """The email edit clears Firebase's `email_verified`, so it must carry a
    fresh set-password link or the parent is locked out of password login."""
    repo = FakeUserEditor()
    invites = RecordingInvites()

    result = await UpdateAdminUser(repo, reader=repo, invites=invites).execute(
        "user-1",
        _edit(email="corrected@example.com"),
        academy_id="acad",
    )

    assert invites.calls == [("user-1", "acad")]
    assert result.user.email == "corrected@example.com"
    assert result.login_invite.status == "sent"
    assert result.login_invite.sent_at == datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_edit_without_email_change_sends_no_invite() -> None:
    repo = FakeUserEditor()
    invites = RecordingInvites()
    use_case = UpdateAdminUser(repo, reader=repo, invites=invites)

    await use_case.execute("user-1", _edit(display_name="Parent Renamed"), academy_id="acad")
    # Same address re-submitted (only the casing differs) is not a change.
    await use_case.execute("user-1", _edit(email="Parent@Example.com"), academy_id="acad")

    assert invites.calls == []


@pytest.mark.asyncio
async def test_failed_invite_is_surfaced_not_swallowed() -> None:
    """The edit has already committed, so the request still succeeds — but the
    admin must be told the parent never got a working link."""
    repo = FakeUserEditor()
    invites = RecordingInvites(fail_with=LoginInviteSendFailed("resend rejected the address"))

    result = await UpdateAdminUser(repo, reader=repo, invites=invites).execute(
        "user-1",
        _edit(email="corrected@example.com"),
        academy_id="acad",
    )

    assert invites.calls == [("user-1", "acad")]
    assert result.user.email == "corrected@example.com"
    assert result.login_invite.status == "failed"
    assert "resend rejected the address" in (result.login_invite.error or "")
