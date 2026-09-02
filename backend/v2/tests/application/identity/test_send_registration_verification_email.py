"""Unit tests for `SendRegistrationVerificationEmail`.

Mirrors `test_send_login_invite.py`: fake verifier/link/sender/cooldown ports,
no Firebase, no Mongo, no email.
"""

from __future__ import annotations

import pytest
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    InviteEmailOutcome,
)
from backend.v2.contexts.identity.application.use_cases.send_registration_verification_email import (
    SendRegistrationVerificationEmail,
)
from backend.v2.contexts.identity.domain.errors import (
    InvalidToken,
    LoginInviteSendFailed,
    VerificationEmailThrottled,
)
from backend.v2.shared.http.errors import DomainError


class FakeVerifier:
    def __init__(self, claims: dict[str, object] | None = None, raises: Exception | None = None):
        self._claims = claims or {}
        self._raises = raises
        self.seen_tokens: list[str] = []

    async def verify(self, id_token: str) -> dict[str, object]:
        self.seen_tokens.append(id_token)
        if self._raises is not None:
            raise self._raises
        return dict(self._claims)


class FakeLinks:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.seen_emails: list[str] = []

    async def generate_email_verification_link(self, email: str) -> str:
        self.seen_emails.append(email)
        if self._raises is not None:
            raise self._raises
        return f"https://verify.example/?email={email}"


class FakeSender:
    def __init__(self, outcome: InviteEmailOutcome | None = None) -> None:
        self._outcome = outcome or InviteEmailOutcome(ok=True)
        self.sent: list[dict[str, str]] = []

    async def send_invite_email(
        self, *, user_id: str, email: str, display_name: str, subject: str, body: str
    ) -> InviteEmailOutcome:
        self.sent.append(
            {
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
                "subject": subject,
                "body": body,
            }
        )
        return self._outcome


class FakeAcademies:
    def __init__(self, name: str | None = "BLNO Badminton") -> None:
        self._name = name

    async def get_academy_name(self, academy_id: str) -> str | None:
        return self._name


class FakeCooldown:
    def __init__(self, allow: bool = True) -> None:
        self._allow = allow
        self.claims: list[str] = []

    async def claim_send(self, email: str) -> bool:
        self.claims.append(email)
        return self._allow


def _use_case(
    *,
    verifier: FakeVerifier | None = None,
    links: FakeLinks | None = None,
    sender: FakeSender | None = None,
    academies: FakeAcademies | None = None,
    cooldown: FakeCooldown | None = None,
) -> tuple[SendRegistrationVerificationEmail, FakeSender, FakeCooldown, FakeLinks]:
    verifier = verifier or FakeVerifier({"email": "parent@example.com", "uid": "uid-1"})
    links = links or FakeLinks()
    sender = sender or FakeSender()
    cooldown = cooldown or FakeCooldown()
    use_case = SendRegistrationVerificationEmail(
        verifier=verifier,
        links=links,
        sender=sender,
        academies=academies or FakeAcademies(),
        cooldown=cooldown,
    )
    return use_case, sender, cooldown, links


@pytest.mark.asyncio
async def test_sends_branded_verification_email_to_the_token_address() -> None:
    use_case, sender, cooldown, links = _use_case()

    await use_case.execute("token-1", academy_id="acad-1")

    assert len(sender.sent) == 1
    sent = sender.sent[0]
    assert sent["email"] == "parent@example.com"
    assert sent["user_id"] == "uid-1"
    assert sent["subject"] == "Verify your email for BLNO Badminton"
    # The Firebase link is generated for the token's address and embedded.
    assert links.seen_emails == ["parent@example.com"]
    assert "https://verify.example/?email=parent@example.com" in sent["body"]
    assert cooldown.claims == ["parent@example.com"]


@pytest.mark.asyncio
async def test_display_name_falls_back_to_the_email_when_the_token_has_no_name() -> None:
    use_case, sender, _, _ = _use_case()

    await use_case.execute("token-1", academy_id="acad-1")

    assert sender.sent[0]["display_name"] == "parent@example.com"


@pytest.mark.asyncio
async def test_unknown_academy_still_sends_with_a_neutral_name() -> None:
    use_case, sender, _, _ = _use_case(academies=FakeAcademies(name=None))

    await use_case.execute("token-1", academy_id="acad-missing")

    assert sender.sent[0]["subject"] == "Verify your email for your academy"


@pytest.mark.asyncio
async def test_token_without_an_email_claim_is_rejected() -> None:
    use_case, sender, _, _ = _use_case(verifier=FakeVerifier({"uid": "uid-1"}))

    with pytest.raises(InvalidToken):
        await use_case.execute("token-1", academy_id="acad-1")
    assert sender.sent == []


@pytest.mark.asyncio
async def test_token_without_a_uid_claim_is_rejected() -> None:
    use_case, sender, _, _ = _use_case(
        verifier=FakeVerifier({"email": "parent@example.com"}),
    )

    with pytest.raises(InvalidToken):
        await use_case.execute("token-1", academy_id="acad-1")
    assert sender.sent == []


@pytest.mark.asyncio
async def test_sub_claim_is_accepted_as_the_uid() -> None:
    use_case, sender, _, _ = _use_case(
        verifier=FakeVerifier({"email": "parent@example.com", "sub": "uid-from-sub"}),
    )

    await use_case.execute("token-1", academy_id="acad-1")

    assert sender.sent[0]["user_id"] == "uid-from-sub"


@pytest.mark.asyncio
async def test_an_unparseable_token_becomes_invalid_token() -> None:
    use_case, sender, _, _ = _use_case(
        verifier=FakeVerifier(raises=ValueError("malformed JWT")),
    )

    with pytest.raises(InvalidToken):
        await use_case.execute("token-1", academy_id="acad-1")
    assert sender.sent == []


class _Outage(DomainError):
    code = "Identity.Outage"
    status_code = 503


@pytest.mark.asyncio
async def test_a_verifier_outage_keeps_its_own_status_instead_of_becoming_a_401() -> None:
    """A Firebase outage must not be reported to the parent as "bad login".

    Collapsing every verifier exception into `InvalidToken` sends a parent off
    to re-authenticate against a service that is down, and hides the incident.
    """
    use_case, _, _, _ = _use_case(verifier=FakeVerifier(raises=_Outage("firebase is down")))

    with pytest.raises(_Outage):
        await use_case.execute("token-1", academy_id="acad-1")


@pytest.mark.asyncio
async def test_a_starlette_style_http_exception_from_the_verifier_is_re_raised() -> None:
    from fastapi import HTTPException

    use_case, _, _, _ = _use_case(
        verifier=FakeVerifier(raises=HTTPException(status_code=503, detail="upstream down")),
    )

    with pytest.raises(HTTPException) as excinfo:
        await use_case.execute("token-1", academy_id="acad-1")
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_a_throttled_address_is_not_mailed_and_no_link_is_generated() -> None:
    """The cooldown is claimed before any work, so a flood costs us nothing."""
    use_case, sender, _, links = _use_case(cooldown=FakeCooldown(allow=False))

    with pytest.raises(VerificationEmailThrottled):
        await use_case.execute("token-1", academy_id="acad-1")

    assert sender.sent == []
    assert links.seen_emails == []


@pytest.mark.asyncio
async def test_a_link_generation_failure_becomes_a_send_failure() -> None:
    use_case, sender, _, _ = _use_case(links=FakeLinks(raises=RuntimeError("firebase boom")))

    with pytest.raises(LoginInviteSendFailed):
        await use_case.execute("token-1", academy_id="acad-1")
    assert sender.sent == []


@pytest.mark.asyncio
async def test_a_sender_reporting_failure_raises_rather_than_reporting_success() -> None:
    use_case, _, _, _ = _use_case(
        sender=FakeSender(InviteEmailOutcome(ok=False, failed_reason="delivery not configured")),
    )

    with pytest.raises(LoginInviteSendFailed) as excinfo:
        await use_case.execute("token-1", academy_id="acad-1")
    assert "delivery not configured" in str(excinfo.value)


def test_verification_body_uses_shared_shell() -> None:
    from backend.v2.contexts.identity.application.use_cases.send_registration_verification_email import (
        _verification_body,
    )
    from backend.v2.shared.comms.email_theme import FONT_STACK

    body = _verification_body(academy_name="A", verify_link="https://x.test")
    assert FONT_STACK in body
    assert "Sent by A" in body
