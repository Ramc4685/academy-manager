from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.identity.application.errors import (
    LoginInviteSendFailed,
    UserNotFound,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    SendLoginInvite,
)


def _user() -> AdminUserDetail:
    return AdminUserDetail(
        user_id="parent-1",
        email="parent@yahoo.com",
        display_name="Pat Parent",
        role="parent",
        status="active",
        phone=None,
        roles=["parent"],
        linked_student_count=1,
        session_count=0,
    )


def _use_case(users, links=None, sender=None, academies=None):
    if links is None:
        links = AsyncMock()
        links.generate_password_reset_link.return_value = "https://reset.example/link"
    if sender is None:
        sender = AsyncMock()
        sender.send.return_value = SendOutcome(
            ok=True, provider_message_id="msg-1", failed_reason=None
        )
    if academies is None:
        academies = AsyncMock()
        academies.get_academy_name.return_value = "Smash Academy"
    return (
        SendLoginInvite(users=users, links=links, sender=sender, academies=academies),
        links,
        sender,
    )


@pytest.mark.asyncio
async def test_sends_branded_set_password_email_and_records_invite():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    use_case, links, sender = _use_case(users)

    result = await use_case.execute("parent-1", academy_id="acad")

    links.generate_password_reset_link.assert_awaited_once_with("parent@yahoo.com")
    sender.send.assert_awaited_once()
    kwargs = sender.send.await_args.kwargs
    assert kwargs["recipient"].email == "parent@yahoo.com"
    assert "Smash Academy" in kwargs["subject"]
    assert "https://reset.example/link" in kwargs["body"]
    users.record_login_invite.assert_awaited_once()
    assert result.sent_at is not None


@pytest.mark.asyncio
async def test_falls_back_to_generic_academy_name():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    academies = AsyncMock()
    academies.get_academy_name.return_value = None
    use_case, _, sender = _use_case(users, academies=academies)

    await use_case.execute("parent-1", academy_id="acad")

    assert "your academy" in sender.send.await_args.kwargs["subject"]


@pytest.mark.asyncio
async def test_raises_when_user_not_found():
    users = AsyncMock()
    users.get_admin_user.return_value = None
    use_case, _, _ = _use_case(users)
    with pytest.raises(UserNotFound):
        await use_case.execute("missing", academy_id="acad")


@pytest.mark.asyncio
async def test_raises_and_does_not_record_when_send_fails():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    sender = AsyncMock()
    sender.send.return_value = SendOutcome(ok=False, provider_message_id=None, failed_reason="boom")
    use_case, _, _ = _use_case(users, sender=sender)

    with pytest.raises(LoginInviteSendFailed):
        await use_case.execute("parent-1", academy_id="acad")
    users.record_login_invite.assert_not_awaited()
