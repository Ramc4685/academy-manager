"""Payment instructions (Settings overhaul Phase 1 Lane C item 5) render,
escaped and whitespace-preserved, in the invoice email body when the owner
has set them — and never appear when empty."""

from __future__ import annotations

import pytest

from backend.v2.composition.email_adapters import InvoiceEmailAdapter
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy
from backend.v2.contexts.identity.domain.models import AcademyMembership, User
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio


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


class _FakePolicies:
    def __init__(self, payment_instructions: str) -> None:
        self._payment_instructions = payment_instructions

    async def get_or_default(self) -> ParentSelfServicePolicy:
        return ParentSelfServicePolicy(
            academy_id="acad", payment_instructions=self._payment_instructions
        )


def _adapter(sender: _FakeSender, *, payment_instructions: str) -> InvoiceEmailAdapter:
    return InvoiceEmailAdapter(
        memberships=_FakeMemberships(),
        users=_FakeUsers(),
        academies=_FakeAcademies(),
        sender=sender,
        self_service_policies=_FakePolicies(payment_instructions),
    )


async def test_payment_instructions_render_in_invoice_email() -> None:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(
            sender, payment_instructions="Pay by Venmo @academy-blno, then email a screenshot."
        ).send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.stripe.test/invoice",
        )
    body = sender.calls[0]["body"]
    assert "Pay by Venmo @academy-blno, then email a screenshot." in body


async def test_payment_instructions_are_escaped() -> None:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(
            sender, payment_instructions='<script>alert(1)</script> & "quoted"'
        ).send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url=None,
        )
    body = sender.calls[0]["body"]
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "&amp;" in body


async def test_empty_payment_instructions_render_nothing() -> None:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, payment_instructions="").send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.stripe.test/invoice",
        )
    # BLNO unchanged: no policy set means no instructions block at all.
    sender2 = _FakeSender()
    with tenant_scope("acad"):
        await InvoiceEmailAdapter(
            memberships=_FakeMemberships(),
            users=_FakeUsers(),
            academies=_FakeAcademies(),
            sender=sender2,
        ).send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.stripe.test/invoice",
        )
    assert sender.calls[0]["body"] == sender2.calls[0]["body"]
