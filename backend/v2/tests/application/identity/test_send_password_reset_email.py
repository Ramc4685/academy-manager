"""Forgot password goes through our branded sender, never reveals accounts."""

from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    InviteEmailOutcome,
)
from backend.v2.contexts.identity.application.use_cases.send_password_reset_email import (
    SendPasswordResetEmail,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership, User

ACADEMY = "acad-1"


def _user() -> User:
    return User(user_id="parent-1", email="parent@example.com", display_name="Pat Parent")


def _membership(status: str = "active") -> AcademyMembership:
    return AcademyMembership(
        membership_id="m-1",
        academy_id=ACADEMY,
        user_id="parent-1",
        roles=("parent",),
        status=status,
    )


def _build(*, user=None, membership=None, cooldown_ok=True, send_ok=True):
    users = AsyncMock()
    users.get_by_email.return_value = user
    memberships = AsyncMock()
    memberships.get_for_user_in_academy.return_value = membership
    links = AsyncMock()
    links.generate_password_reset_link.return_value = "https://blno.example/auth/action?oobCode=x"
    sender = AsyncMock()
    sender.send_invite_email.return_value = InviteEmailOutcome(
        ok=send_ok, failed_reason=None if send_ok else "provider down"
    )
    academies = AsyncMock()
    academies.get_academy_name.return_value = "Smash Academy"
    cooldown = AsyncMock()
    cooldown.claim_send.return_value = cooldown_ok
    portals = AsyncMock()
    portals.get_academy_portal_url.return_value = "https://blno.example"
    use_case = SendPasswordResetEmail(
        users=users,
        memberships=memberships,
        links=links,
        sender=sender,
        academies=academies,
        cooldown=cooldown,
        portals=portals,
    )
    return use_case, links, sender, cooldown


@pytest.mark.asyncio
async def test_member_gets_branded_reset_link_on_their_academy_portal() -> None:
    use_case, links, sender, _ = _build(user=_user(), membership=_membership())

    await use_case.execute(" parent@example.com ", academy_id=ACADEMY)

    links.generate_password_reset_link.assert_awaited_once_with(
        "parent@example.com",
        uid="parent-1",
        display_name="Pat Parent",
        portal_url="https://blno.example",
    )
    kwargs = sender.send_invite_email.await_args.kwargs
    assert kwargs["email"] == "parent@example.com"
    assert "Smash Academy" in kwargs["subject"]
    assert "https://blno.example/auth/action?oobCode=x" in kwargs["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "membership"),
    [(None, None), (_user(), None), (_user(), _membership(status="suspended"))],
    ids=["unknown-email", "no-membership-here", "inactive-membership"],
)
async def test_non_members_get_nothing_and_no_error(user, membership) -> None:
    use_case, links, sender, cooldown = _build(user=user, membership=membership)

    await use_case.execute("someone@example.com", academy_id=ACADEMY)

    links.generate_password_reset_link.assert_not_awaited()
    sender.send_invite_email.assert_not_awaited()
    cooldown.claim_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_throttled_mailbox_sends_nothing_silently() -> None:
    use_case, links, sender, _ = _build(user=_user(), membership=_membership(), cooldown_ok=False)

    await use_case.execute("parent@example.com", academy_id=ACADEMY)

    links.generate_password_reset_link.assert_not_awaited()
    sender.send_invite_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_does_not_surface_to_the_anonymous_caller() -> None:
    use_case, _, sender, _ = _build(user=_user(), membership=_membership(), send_ok=False)

    await use_case.execute("parent@example.com", academy_id=ACADEMY)  # no raise

    sender.send_invite_email.assert_awaited_once()
