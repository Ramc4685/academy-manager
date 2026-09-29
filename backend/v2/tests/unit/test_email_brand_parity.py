"""Money and account emails carry the full academy brand (hardcoded-values row 6).

Golden pin for BLNO: an academy document that holds only a name (no logo,
no brand colour, no contact details) must render every money/account email
byte-for-byte as it did before the full brand was wired in. The fixtures in
``tests/fixtures/email_brand_parity/`` were captured from the pre-change code;
never regenerate them to make this test pass.

The second half shows what the change adds: an academy with a logo, a colour
and contact details gets them in the shell, and hostile values are escaped or
dropped.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import mongomock_motor
import pytest

from backend.v2.composition.dispute_notices import DisputeNoticeEmailAdapter
from backend.v2.composition.email_adapters import (
    DuesReminderEmailAdapter,
    InvoiceEmailAdapter,
    InvoiceNaming,
    LastCharge,
)
from backend.v2.contexts.billing.application.ports import (
    InviteEmailOutcome as BillingInviteOutcome,
)
from backend.v2.contexts.billing.application.ports import ParentContact
from backend.v2.contexts.billing.application.use_cases.send_add_card_reminder import (
    SendAddCardReminder,
)
from backend.v2.contexts.billing.domain.events import PaymentDisputeNoticePayload
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.identity.application.use_cases.admin_directory import AdminUserDetail
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    InviteEmailOutcome,
    SendLoginInvite,
)
from backend.v2.contexts.identity.application.use_cases.send_registration_verification_email import (
    SendRegistrationVerificationEmail,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership, User
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "email_brand_parity"

ACADEMY_ID = "blno"
NAME_ONLY_DOC: dict[str, Any] = {"academy_id": ACADEMY_ID, "display_name": "BLNO Badminton"}
BRANDED_DOC: dict[str, Any] = {
    "academy_id": ACADEMY_ID,
    "display_name": "BLNO Badminton",
    "logo_url": "https://cdn.example.test/blno-logo.png",
    "brand_color": "#0F766E",
    "contact_email": "desk@blno.example.test",
    "contact_phone": "+1 555 0100",
}

NAMING = InvoiceNaming(
    student_name="Arjun",
    session_label="Sat 9:00 AM Beginners",
    invoice_number="BLNO-2026-09-0042",
    last_charge=LastCharge(
        amount_cents=7_000, currency="usd", period="2026-08", charged_on=date(2026, 8, 3)
    ),
)


async def _parity_return_url_for(academy_id: str) -> str:
    return "https://app.example.test/parent/payments"


class _Academies:
    """Academy repo fake: ``find_by_id`` returns the stored document and
    ``get_academy_name`` mirrors ``MongoAcademyRepository`` exactly."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs
        self.looked_up: list[str] = []

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        self.looked_up.append(academy_id)
        return self._docs.get(academy_id)

    async def get_academy_name(self, academy_id: str) -> str | None:
        doc = self._docs.get(academy_id)
        if doc is None:
            return None
        name = doc.get("display_name") or doc.get("name")
        return str(name) if name else None


class _Sender:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> SendOutcome:
        self.sent.append(kwargs)
        return SendOutcome(ok=True, provider_message_id="msg", failed_reason=None)


class _InviteSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_invite_email(self, **kwargs: Any) -> InviteEmailOutcome:
        self.sent.append(kwargs)
        return InviteEmailOutcome(ok=True)


class _BillingInviteSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_invite_email(self, **kwargs: Any) -> BillingInviteOutcome:
        self.sent.append(kwargs)
        return BillingInviteOutcome(ok=True)


class _Memberships:
    async def get_membership(self, academy_id: str, user_id: str) -> AcademyMembership:
        return AcademyMembership(
            membership_id="mem-1",
            academy_id=academy_id,
            user_id=user_id,
            roles=("parent",),
            status="active",
        )


class _Users:
    async def get_by_id(self, user_id: str) -> User:
        return User(user_id=user_id, email="parent@example.com", display_name="Parent One")


class _OwnerUsers:
    async def get_by_id(self, user_id: str) -> Any:
        return SimpleNamespace(email="owner@example.com", display_name="Owner")


class _Contacts:
    async def get_parent_contact(self, parent_id: str, *, academy_id: str) -> ParentContact:
        return ParentContact(parent_id=parent_id, email="parent@example.com", display_name="Pat")


class _CardLinks:
    async def create_card_setup_link(
        self, *, parent_id: str, academy_id: str, return_url: str
    ) -> str:
        return "https://app.example.test/parent/payments?setup=1"


class _ResetLinks:
    async def generate_password_reset_link(self, email: str, **_: Any) -> str:
        return "https://reset.example.test/link?oob=abc"


class _VerifyLinks:
    async def generate_email_verification_link(self, email: str) -> str:
        return "https://verify.example.test/?oob=xyz"


class _Verifier:
    async def verify(self, id_token: str) -> dict[str, object]:
        return {"email": "parent@example.com", "uid": "uid-1", "name": "Pat"}


class _Cooldown:
    async def claim_send(self, email: str) -> bool:
        return True


class _AdminUsers:
    async def get_admin_user(self, user_id: str, *, academy_id: str) -> AdminUserDetail:
        return AdminUserDetail(
            user_id=user_id,
            email="parent@example.com",
            display_name="Pat Parent",
            role="parent",
            status="active",
            phone=None,
            roles=["parent"],
            linked_student_count=1,
            session_count=0,
        )

    async def record_login_invite(
        self, user_id: str, *, academy_id: str, sent_at: datetime
    ) -> None:
        return None


async def _naming(_: str) -> InvoiceNaming:
    return NAMING


def _brand_kwargs(academies: _Academies) -> dict[str, Any]:
    """The brand lookup the composition root wires into the context use cases."""
    from backend.v2.shared.comms.email_brand import AcademyEmailBrands

    return {"brands": AcademyEmailBrands(academies)}


async def render_all(doc: dict[str, Any]) -> dict[str, str]:
    """Every money/account email body for one academy document, keyed by name."""
    academies = _Academies({ACADEMY_ID: doc})
    bodies: dict[str, str] = {}
    with tenant_scope(ACADEMY_ID):
        sender = _Sender()
        invoices = InvoiceEmailAdapter(
            memberships=_Memberships(),  # type: ignore[arg-type]
            users=_Users(),  # type: ignore[arg-type]
            academies=academies,  # type: ignore[arg-type]
            sender=sender,
            naming=_naming,
        )
        await invoices.send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.example.test/pay",
        )
        await invoices.send_dunning_notice(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            balance_due_cents=7_000,
            currency="usd",
            attempt_no=2,
            terminal=False,
        )
        await invoices.send_autopay_notice(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
            charge_on=date(2026, 9, 8),
            portal_url="https://portal.example.test/parent/payments",
        )
        await invoices.send_autopay_receipt(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
        )
        dues = DuesReminderEmailAdapter(
            academies=academies,  # type: ignore[arg-type]
            sender=sender,
            naming=_naming,
        )
        await dues.send_past_due_reminder(
            parent_id="parent-1",
            email="parent@example.com",
            display_name="Parent One",
            invoice_id="inv-1",
            period="2026-09",
            balance_due_cents=7_000,
            currency="usd",
            days_past_due=5,
            pay_url="https://portal.example.test/pay",
        )
        await dues.send_reminder(
            parent_id="parent-1",
            email="parent@example.com",
            display_name="Parent One",
            total_due_cents=14_000,
            pending_count=2,
            currency="usd",
            pay_url="https://portal.example.test/pay",
        )
        names = [
            "invoice",
            "dunning",
            "autopay_notice",
            "autopay_receipt",
            "past_due_reminder",
            "manual_reminder",
        ]
        for name, call in zip(names, sender.sent, strict=True):
            bodies[name] = call["body"]

        db = mongomock_motor.AsyncMongoMockClient()["parity"]
        await db["academy_memberships"].insert_one(
            {"academy_id": ACADEMY_ID, "user_id": "owner-1", "roles": ["owner"], "status": "active"}
        )
        dispute_sender = _Sender()
        await DisputeNoticeEmailAdapter(
            db=db, users=_OwnerUsers(), academies=academies, sender=dispute_sender
        ).send_dispute_notice(
            payload=PaymentDisputeNoticePayload(
                kind="opened",
                dispute_id="dp_1",
                payment_id="pay_1",
                amount_cents=7_000,
                currency="usd",
                reason="fraudulent",
                status="needs_response",
                evidence_due_by=datetime(2026, 10, 1, tzinfo=UTC),
            )
        )
        bodies["dispute_notice"] = dispute_sender.sent[0]["body"]

    card_sender = _BillingInviteSender()
    await SendAddCardReminder(
        contacts=_Contacts(),
        links=_CardLinks(),
        sender=card_sender,
        academies=academies,
        return_url_for=_parity_return_url_for,
        **_brand_kwargs(academies),
    ).execute(academy_id=ACADEMY_ID, parent_id="parent-1")
    bodies["add_card"] = card_sender.sent[0]["body"]

    invite_sender = _InviteSender()
    await SendLoginInvite(
        users=_AdminUsers(),
        links=_ResetLinks(),
        sender=invite_sender,
        academies=academies,
        **_brand_kwargs(academies),
    ).execute("parent-1", academy_id=ACADEMY_ID)
    bodies["login_invite"] = invite_sender.sent[0]["body"]

    verify_sender = _InviteSender()
    await SendRegistrationVerificationEmail(
        verifier=_Verifier(),
        links=_VerifyLinks(),
        sender=verify_sender,
        academies=academies,
        cooldown=_Cooldown(),
        **_brand_kwargs(academies),
    ).execute("token", academy_id=ACADEMY_ID)
    bodies["verification"] = verify_sender.sent[0]["body"]
    return bodies


EMAILS = [
    "invoice",
    "dunning",
    "autopay_notice",
    "autopay_receipt",
    "past_due_reminder",
    "manual_reminder",
    "dispute_notice",
    "add_card",
    "login_invite",
    "verification",
]


def _golden(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", EMAILS)
async def test_name_only_academy_renders_byte_identical_to_before(name: str) -> None:
    bodies = await render_all(NAME_ONLY_DOC)
    assert bodies[name] == _golden(name)


@pytest.mark.parametrize("name", EMAILS)
async def test_branded_academy_shows_logo_colour_and_contact_footer(name: str) -> None:
    body = (await render_all(BRANDED_DOC))[name]
    assert '<img src="https://cdn.example.test/blno-logo.png" alt="BLNO Badminton"' in body
    assert "background:#0f766e" in body
    assert "Sent by BLNO Badminton<br />desk@blno.example.test &middot; +1 555 0100" in body
    # The copy itself does not move: the body text between the header and the
    # footer is the name-only golden's.
    golden = _golden(name)
    inner_start = golden.index('<div style="height:3px;width:48px;')
    inner_end = golden.index("Sent by BLNO Badminton")
    assert golden[inner_start:inner_end] in body


async def test_hostile_academy_values_are_escaped_or_dropped() -> None:
    bodies = await render_all(
        {
            "academy_id": ACADEMY_ID,
            "display_name": "BLNO <b>Badminton</b>",
            "logo_url": 'javascript:alert(1)//"><script>',
            "brand_color": "red;background:url(x)",
            "contact_email": "<script>alert(1)</script>",
            "contact_phone": 12345,
        }
    )
    for body in bodies.values():
        assert "javascript:" not in body
        assert "<script>" not in body
        assert "<img" not in body
        assert "url(x)" not in body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
        assert "12345" not in body
        assert "BLNO &lt;b&gt;Badminton&lt;/b&gt;" in body


async def test_http_logo_is_not_embedded() -> None:
    bodies = await render_all({**NAME_ONLY_DOC, "logo_url": "http://cdn.example.test/logo.png"})
    for name in EMAILS:
        assert bodies[name] == _golden(name)


async def test_brand_lookup_reads_only_the_request_academy() -> None:
    other = {"academy_id": "other", "display_name": "Other", "logo_url": "https://x.test/o.png"}
    academies = _Academies({ACADEMY_ID: NAME_ONLY_DOC, "other": other})
    sender = _Sender()
    dues = DuesReminderEmailAdapter(academies=academies, sender=sender)  # type: ignore[arg-type]
    with tenant_scope(ACADEMY_ID):
        await dues.send_reminder(
            parent_id="p",
            email="p@example.com",
            display_name=None,
            total_due_cents=100,
            pending_count=1,
            currency="usd",
            pay_url=None,
        )
    assert set(academies.looked_up) == {ACADEMY_ID}
    assert "x.test/o.png" not in sender.sent[0]["body"]


async def test_a_failing_brand_lookup_never_costs_the_send() -> None:
    class _Broken(_Academies):
        async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
            raise RuntimeError("mongo down")

    sender = _Sender()
    dues = DuesReminderEmailAdapter(
        academies=_Broken({ACADEMY_ID: NAME_ONLY_DOC}),  # type: ignore[arg-type]
        sender=sender,
    )
    with tenant_scope(ACADEMY_ID):
        ok = await dues.send_reminder(
            parent_id="parent-1",
            email="parent@example.com",
            display_name="Parent One",
            total_due_cents=14_000,
            pending_count=2,
            currency="usd",
            pay_url="https://portal.example.test/pay",
        )
    assert ok is True
    assert sender.sent[0]["body"] == _golden("manual_reminder")
