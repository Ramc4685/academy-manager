"""Interface tests for POST /admin/students/{student_id}/login-invite (UIM12).

The flag gate is the point of these tests: `enable_student_login` is the
incident kill switch, and with it off the invite route must not be able to
mint a Firebase account, grant a `student` membership, or send mail — even
for a legitimate admin.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    LoginInviteResult,
)
from backend.v2.shared.config import get_settings


class _FakeProvisionStudentLogin:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def execute(self, command, *, academy_id: str) -> str:
        self.calls.append(command)
        return "p-1"  # a user the conftest invite sender knows


class _FakeInvite:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def execute(self, user_id: str, *, academy_id: str) -> LoginInviteResult:
        self.sent.append(user_id)
        return LoginInviteResult(sent_at=datetime.now(UTC))


@pytest.fixture
def student_login_flag(monkeypatch):
    """Turn `enable_student_login` on for the duration of a test."""

    def _set(enabled: bool) -> None:
        monkeypatch.setenv("V2_ENABLE_STUDENT_LOGIN", "true" if enabled else "false")
        get_settings.cache_clear()

    try:
        yield _set
    finally:
        get_settings.cache_clear()


def _wire(admin_client) -> tuple[_FakeProvisionStudentLogin, _FakeInvite]:
    provision = _FakeProvisionStudentLogin()
    invite = _FakeInvite()
    admin_client.use_cases.provision_student_login = provision
    admin_client.use_cases.send_login_invite = invite
    return provision, invite


def test_login_invite_404s_when_flag_off(admin_client, student_login_flag):
    provision, invite = _wire(admin_client)
    student_login_flag(False)

    r = admin_client.post(
        "/api/v2/admin/students/st-1/login-invite",
        json={"email": "student@example.com", "display_name": "Alex Chen"},
    )

    assert r.status_code == 404
    # The kill switch is only real if nothing happened: no Firebase account,
    # no membership, no email.
    assert provision.calls == []
    assert invite.sent == []


def test_login_invite_succeeds_when_flag_on(admin_client, student_login_flag):
    provision, invite = _wire(admin_client)
    student_login_flag(True)

    r = admin_client.post(
        "/api/v2/admin/students/st-1/login-invite",
        json={"email": "student@example.com", "display_name": "Alex Chen"},
    )

    assert r.status_code == 200, r.text
    assert len(provision.calls) == 1
    assert invite.sent == ["p-1"]


def test_login_invite_threads_reason_into_the_command(admin_client, student_login_flag):
    provision, _ = _wire(admin_client)
    student_login_flag(True)

    r = admin_client.post(
        "/api/v2/admin/students/st-1/login-invite",
        json={
            "email": "student@example.com",
            "display_name": "Alex Chen",
            "reason": "parent asked for teen portal access",
        },
    )

    assert r.status_code == 200, r.text
    assert provision.calls[0].reason == "parent asked for teen portal access"


def test_login_invite_wrong_persona_404(coach_on_admin_client, student_login_flag):
    student_login_flag(True)

    r = coach_on_admin_client.post(
        "/api/v2/admin/students/st-1/login-invite",
        json={"email": "student@example.com", "display_name": "Alex Chen"},
    )

    assert r.status_code == 404
