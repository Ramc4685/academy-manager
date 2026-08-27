from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.identity.application.errors import (
    LoginInviteSendFailed,
    UserNotFound,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    InviteEmailOutcome,
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


def _use_case(users, links=None, sender=None, academies=None, portals=None):
    if links is None:
        links = AsyncMock()
        links.generate_password_reset_link.return_value = "https://reset.example/link"
    if sender is None:
        sender = AsyncMock()
        sender.send_invite_email.return_value = InviteEmailOutcome(ok=True, failed_reason=None)
    if academies is None:
        academies = AsyncMock()
        academies.get_academy_name.return_value = "Smash Academy"
    if portals is None:
        portals = AsyncMock()
        portals.get_academy_portal_url.return_value = "https://blno-academy.courtmastr.com"
    return (
        SendLoginInvite(
            users=users, links=links, sender=sender, academies=academies, portals=portals
        ),
        links,
        sender,
    )


@pytest.mark.asyncio
async def test_sends_branded_set_password_email_and_records_invite():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    use_case, links, sender = _use_case(users)

    result = await use_case.execute("parent-1", academy_id="acad")

    links.generate_password_reset_link.assert_awaited_once_with(
        "parent@yahoo.com",
        uid="parent-1",
        display_name="Pat Parent",
        portal_url="https://blno-academy.courtmastr.com",
    )
    sender.send_invite_email.assert_awaited_once()
    kwargs = sender.send_invite_email.await_args.kwargs
    assert kwargs["email"] == "parent@yahoo.com"
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

    assert "your academy" in sender.send_invite_email.await_args.kwargs["subject"]


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
    sender.send_invite_email.return_value = InviteEmailOutcome(ok=False, failed_reason="boom")
    use_case, _, _ = _use_case(users, sender=sender)

    with pytest.raises(LoginInviteSendFailed):
        await use_case.execute("parent-1", academy_id="acad")
    users.record_login_invite.assert_not_awaited()


@pytest.mark.asyncio
async def test_passes_uid_and_display_name_to_reset_link_port_for_self_heal():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    use_case, links, _ = _use_case(users)

    await use_case.execute("parent-1", academy_id="acad")

    links.generate_password_reset_link.assert_awaited_once_with(
        "parent@yahoo.com",
        uid="parent-1",
        display_name="Pat Parent",
        portal_url="https://blno-academy.courtmastr.com",
    )


@pytest.mark.asyncio
async def test_wraps_unexpected_reset_link_error_as_send_failed():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    links = AsyncMock()
    links.generate_password_reset_link.side_effect = RuntimeError("firebase unreachable")
    use_case, _, sender = _use_case(users, links=links)

    with pytest.raises(LoginInviteSendFailed):
        await use_case.execute("parent-1", academy_id="acad")
    sender.send_invite_email.assert_not_awaited()
    users.record_login_invite.assert_not_awaited()


@pytest.mark.asyncio
async def test_wraps_unexpected_academy_name_error_as_send_failed():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    academies = AsyncMock()
    academies.get_academy_name.side_effect = RuntimeError("db unreachable")
    use_case, _, sender = _use_case(users, academies=academies)

    with pytest.raises(LoginInviteSendFailed):
        await use_case.execute("parent-1", academy_id="acad")
    sender.send_invite_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_passes_each_academys_own_portal_url_to_the_reset_link_port():
    """ADR-0007: the invite must carry the recipient academy's own host, not a
    single deployment-wide FRONTEND_URL, or the parent lands on another tenant."""
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    portals = AsyncMock()
    portals.get_academy_portal_url.return_value = "https://other-academy.courtmastr.com"
    use_case, links, _ = _use_case(users, portals=portals)

    await use_case.execute("parent-1", academy_id="other")

    portals.get_academy_portal_url.assert_awaited_once_with("other")
    assert (
        links.generate_password_reset_link.await_args.kwargs["portal_url"]
        == "https://other-academy.courtmastr.com"
    )


@pytest.mark.asyncio
async def test_sends_without_portal_url_when_academy_has_no_resolvable_host():
    """A missing slug must not block the invite — the link simply falls back to
    Firebase's own hosted page rather than the branded in-app handler."""
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    portals = AsyncMock()
    portals.get_academy_portal_url.return_value = None
    use_case, links, sender = _use_case(users, portals=portals)

    await use_case.execute("parent-1", academy_id="acad")

    assert links.generate_password_reset_link.await_args.kwargs["portal_url"] is None
    sender.send_invite_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_wraps_unexpected_portal_lookup_error_as_send_failed():
    users = AsyncMock()
    users.get_admin_user.return_value = _user()
    portals = AsyncMock()
    portals.get_academy_portal_url.side_effect = RuntimeError("db unreachable")
    use_case, _, sender = _use_case(users, portals=portals)

    with pytest.raises(LoginInviteSendFailed):
        await use_case.execute("parent-1", academy_id="acad")
    sender.send_invite_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_escapes_display_name_in_login_invite_html():
    users = AsyncMock()
    users.get_admin_user.return_value = _user().model_copy(
        update={"display_name": '<img src=x onerror="alert(1)">'},
    )
    use_case, _, sender = _use_case(users)

    await use_case.execute("parent-1", academy_id="acad")

    body = sender.send_invite_email.await_args.kwargs["body"]
    assert "<img" not in body
    assert "&lt;img" in body
