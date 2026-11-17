"""Billing emails carry the academy's From display name and Reply-To (L11
item 2), and the autopay-failed email can carry a one-time sign-in link to
the pay page (L11 item 1)."""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.composition.email_adapters import (
    AddCardReminderEmailAdapter,
    DuesReminderEmailAdapter,
    InvoiceEmailAdapter,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.unit.test_invoice_email_naming import (
    _FakeMemberships,
    _FakeSender,
    _FakeUsers,
)

_DOC = {
    "academy_id": "acad",
    "display_name": "Synthetic Academy",
    "support_email": "desk@example.com",
}


class _Academies:
    async def get_academy_name(self, academy_id: str) -> str:
        return "Synthetic Academy"

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        return _DOC if academy_id == "acad" else None


async def _pay_link(academy_id: str) -> tuple[str | None, str]:
    return "https://synthetic.example.test/parent/payments", "Synthetic Academy"


def _invoices(sender: _FakeSender, **kwargs: Any) -> InvoiceEmailAdapter:
    return InvoiceEmailAdapter(
        memberships=_FakeMemberships(),  # type: ignore[arg-type]
        users=_FakeUsers(),  # type: ignore[arg-type]
        academies=_Academies(),  # type: ignore[arg-type]
        sender=sender,
        pay_page_url="https://synthetic.example.test/parent/payments",
        pay_link=_pay_link,
        **kwargs,
    )


_DUNNING = {
    "parent_id": "parent-1",
    "invoice_id": "inv-1",
    "period": "2026-09",
    "balance_due_cents": 7_000,
    "currency": "usd",
    "attempt_no": 1,
    "terminal": False,
}


def _assert_identity(call: dict[str, Any]) -> None:
    assert call["sender_name"] == "Synthetic Academy"
    assert call["reply_to"] == "desk@example.com"


async def test_every_invoice_adapter_email_carries_the_academy_identity() -> None:
    sender = _FakeSender()
    adapter = _invoices(sender)
    with tenant_scope("acad"):
        await adapter.send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.example.test/s",
        )
        await adapter.send_dunning_notice(**_DUNNING)
        await adapter.send_autopay_notice(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
            charge_on=__import__("datetime").date(2026, 9, 3),
            portal_url=None,
        )
        await adapter.send_payment_receipt(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            amount_cents=7_000,
            currency="usd",
        )
    assert len(sender.calls) == 4
    for call in sender.calls:
        _assert_identity(call)


async def test_dues_reminders_and_add_card_carry_the_academy_identity() -> None:
    sender = _FakeSender()
    dues = DuesReminderEmailAdapter(academies=_Academies(), sender=sender)  # type: ignore[arg-type]
    add_card = AddCardReminderEmailAdapter(sender=sender, academies=_Academies())
    with tenant_scope("acad"):
        await dues.send_past_due_reminder(
            parent_id="parent-1",
            email="parent@example.com",
            display_name="Parent One",
            invoice_id="inv-1",
            period="2026-09",
            balance_due_cents=7_000,
            currency="usd",
            days_past_due=3,
            pay_url=None,
        )
        await dues.send_reminder(
            parent_id="parent-1",
            email="parent@example.com",
            display_name="Parent One",
            total_due_cents=7_000,
            pending_count=1,
            currency="usd",
            pay_url=None,
        )
        await add_card.send_invite_email(
            user_id="parent-1", email="parent@example.com", display_name="P", subject="s", body="b"
        )
    assert len(sender.calls) == 3
    for call in sender.calls:
        _assert_identity(call)


async def test_an_academy_lookup_failure_never_costs_the_send() -> None:
    class _Broken(_Academies):
        async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
            raise RuntimeError("mongo down")

    sender = _FakeSender()
    adapter = InvoiceEmailAdapter(
        memberships=_FakeMemberships(),  # type: ignore[arg-type]
        users=_FakeUsers(),  # type: ignore[arg-type]
        academies=_Broken(),  # type: ignore[arg-type]
        sender=sender,
        pay_link=_pay_link,
    )
    with tenant_scope("acad"):
        await adapter.send_dunning_notice(**_DUNNING)
    assert sender.calls[0]["sender_name"] is None
    assert sender.calls[0]["reply_to"] is None


# -- item 1: the dunning button is a plain pay-page link, never a sign-in token ---


@pytest.mark.parametrize("roles", [("parent",), ("parent", "admin", "coach")])
async def test_dunning_link_carries_no_sign_in_token(roles: tuple[str, ...]) -> None:
    """Security review (L11): a forwarded or leaked billing email must not
    yield a session, least of all for a parent who is also staff. The button
    is the bare pay page; nothing in the email can be redeemed for a login."""
    import re

    from backend.v2.contexts.identity.domain.models import AcademyMembership

    class _Memberships:
        async def get_membership(self, academy_id: str, user_id: str) -> AcademyMembership:
            return AcademyMembership(
                membership_id="m",
                academy_id=academy_id,
                user_id=user_id,
                roles=roles,
                status="active",
            )

    sender = _FakeSender()
    adapter = InvoiceEmailAdapter(
        memberships=_Memberships(),  # type: ignore[arg-type]
        users=_FakeUsers(),  # type: ignore[arg-type]
        academies=_Academies(),  # type: ignore[arg-type]
        sender=sender,
        pay_link=_pay_link,
    )
    with tenant_scope("acad"):
        await adapter.send_dunning_notice(**_DUNNING)
    body = sender.calls[0]["body"]
    hrefs = re.findall(r'href="([^"]+)"', body)
    pay = [h for h in hrefs if "synthetic.example.test" in h]
    assert pay == ["https://synthetic.example.test/parent/payments?pay=inv-1"]
    assert "/auth/magic" not in body
    assert "t=" not in pay[0]
    assert not hasattr(adapter, "_signed_pay_link")
