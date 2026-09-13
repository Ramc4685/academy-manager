"""Parent-facing billing emails name the tuition month, student and class (#659).

Incident 2026-09-05: nine families read "$70.00 will be charged on Sep 08 for
2026-09" as a second charge for the month they had just paid, because no
parent-facing email ever said *which* month, *which* child, or *which* class.
These tests pin the copy rules the owner decided on 2026-09-12:

* the tuition month is always rendered in words ("September 2026");
* the student and the class line are named when they can be resolved;
* a raw period code or a raw internal ``invoice_id`` never reaches a parent.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.composition.email_adapters import InvoiceEmailAdapter, InvoiceNaming, LastCharge
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.identity.domain.models import AcademyMembership, User
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

RAW_INVOICE_ID = "inv-monthly-enr_28520c4d1b15c9538512-2026-09"


class _FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, **kwargs) -> SendOutcome:
        self.calls.append(kwargs)
        return SendOutcome(ok=True, provider_message_id="msg_test", failed_reason=None)


class _FakeMemberships:
    async def get_membership(self, academy_id: str, user_id: str) -> AcademyMembership:
        return AcademyMembership(
            membership_id="mem-1",
            academy_id=academy_id,
            user_id=user_id,
            roles=("parent",),
            status="active",
        )


class _FakeUsers:
    async def get_by_id(self, user_id: str) -> User:
        return User(user_id=user_id, email="parent@example.com", display_name="Parent One")


class _FakeAcademies:
    async def get_academy_name(self, academy_id: str) -> str:
        return "Test Academy"


def _adapter(sender: _FakeSender, *, naming: InvoiceNaming | None) -> InvoiceEmailAdapter:
    async def describe(invoice_id: str) -> InvoiceNaming | None:
        return naming

    return InvoiceEmailAdapter(
        memberships=_FakeMemberships(),
        users=_FakeUsers(),
        academies=_FakeAcademies(),
        sender=sender,
        naming=describe,
    )


_FULL_NAMING = InvoiceNaming(
    student_name="Arjun",
    session_label="Sat 9:00 AM Beginners",
    invoice_number="BLNO-2026-09-0042",
)


async def test_invoice_email_names_month_student_and_class() -> None:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, naming=_FULL_NAMING).send_invoice_email(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.stripe.test/invoice",
        )

    call = sender.calls[0]
    assert "September 2026" in call["subject"]
    assert "Arjun" in call["subject"]
    assert "Sat 9:00 AM Beginners" in call["subject"]
    assert "September 2026" in call["body"]
    assert "Arjun" in call["body"]
    assert "Sat 9:00 AM Beginners" in call["body"]
    assert "BLNO-2026-09-0042" in call["body"]


async def test_autopay_notice_names_month_student_and_class() -> None:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, naming=_FULL_NAMING).send_autopay_notice(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
            charge_on=date(2026, 9, 8),
            portal_url="https://app.test/parent/payments",
        )

    call = sender.calls[0]
    assert "September 2026 tuition" in call["subject"]
    assert "Arjun" in call["subject"]
    assert "September 2026 tuition" in call["body"]
    assert "Arjun" in call["body"]
    assert "Sat 9:00 AM Beginners" in call["body"]


async def test_autopay_receipt_names_month_and_student() -> None:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, naming=_FULL_NAMING).send_autopay_receipt(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
        )

    call = sender.calls[0]
    assert "September 2026 tuition" in call["subject"]
    assert "September 2026 tuition" in call["body"]
    assert "Arjun" in call["body"]


async def test_dunning_notice_names_month_and_student() -> None:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, naming=_FULL_NAMING).send_dunning_notice(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            balance_due_cents=7_000,
            currency="usd",
            attempt_no=2,
            terminal=False,
        )

    call = sender.calls[0]
    assert "September 2026 tuition" in call["subject"]
    assert "Arjun" in call["body"]


@pytest.mark.parametrize(
    "naming",
    [None, InvoiceNaming()],
    ids=["unresolved", "empty"],
)
async def test_emails_never_leak_raw_period_or_invoice_id(naming: InvoiceNaming | None) -> None:
    """Even with nothing resolvable, the parent sees a month in words — never
    ``2026-09`` and never the internal id."""
    sender = _FakeSender()
    adapter = _adapter(sender, naming=naming)
    with tenant_scope("acad"):
        await adapter.send_invoice_email(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url=None,
        )
        await adapter.send_autopay_notice(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
            charge_on=date(2026, 9, 8),
            portal_url=None,
        )
        await adapter.send_autopay_receipt(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
        )
        await adapter.send_dunning_notice(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            balance_due_cents=7_000,
            currency="usd",
            attempt_no=3,
            terminal=True,
        )

    assert len(sender.calls) == 4
    for call in sender.calls:
        blob = f"{call['subject']} {call['body']}"
        assert "September 2026" in blob
        assert "2026-09" not in blob
        assert RAW_INVOICE_ID not in blob


async def test_adapter_survives_a_failing_naming_resolver() -> None:
    """A student lookup that blows up must not cost the parent their invoice."""
    sender = _FakeSender()

    async def describe(invoice_id: str) -> InvoiceNaming:
        raise RuntimeError("mongo is down")

    adapter = InvoiceEmailAdapter(
        memberships=_FakeMemberships(),
        users=_FakeUsers(),
        academies=_FakeAcademies(),
        sender=sender,
        naming=describe,
    )

    with tenant_scope("acad"):
        await adapter.send_invoice_email(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url=None,
        )

    assert "September 2026" in sender.calls[0]["subject"]


_LAST_CHARGE = LastCharge(
    amount_cents=7_000,
    currency="usd",
    period="2026-08",
    charged_on=date(2026, 9, 3),
)


async def test_autopay_notice_explains_the_previous_month_charge() -> None:
    """The sentence the incident asked for: two charges five days apart only
    read as one duplicate while the earlier one is unnamed (#659)."""
    sender = _FakeSender()
    naming = _FULL_NAMING.model_copy(update={"last_charge": _LAST_CHARGE})
    with tenant_scope("acad"):
        await _adapter(sender, naming=naming).send_autopay_notice(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
            charge_on=date(2026, 9, 8),
            portal_url="https://app.test/parent/payments",
        )

    body = sender.calls[0]["body"]
    assert "Your last charge was" in body
    assert "$70.00 for August 2026 tuition on September 3" in body


async def test_autopay_receipt_explains_the_previous_month_charge() -> None:
    sender = _FakeSender()
    naming = _FULL_NAMING.model_copy(update={"last_charge": _LAST_CHARGE})
    with tenant_scope("acad"):
        await _adapter(sender, naming=naming).send_autopay_receipt(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
        )

    assert "$70.00 for August 2026 tuition on September 3" in sender.calls[0]["body"]


async def test_no_last_charge_sentence_when_there_is_no_recent_charge() -> None:
    """Silence, not "no previous charge": a first-month family must not be told
    anything about a payment history they do not have."""
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, naming=_FULL_NAMING).send_autopay_notice(
            parent_id="parent-1",
            invoice_id=RAW_INVOICE_ID,
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
            charge_on=date(2026, 9, 8),
            portal_url=None,
        )

    assert "last charge" not in sender.calls[0]["body"].lower()
