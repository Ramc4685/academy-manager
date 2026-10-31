"""Invoice email copies to opted-in family contacts on a real ``mongod`` (L1b2).

``real_db`` replays every migration, so the production ``family_contacts``
indexes (0196) and the ``invoice_contact_email_sends`` unique claim key (0197)
exist. The adapter under test is the real ``InvoiceEmailAdapter`` wired with
the real ``InvoiceContactCopies`` (real contacts repository, real claim
repository); only identity lookups and the provider are stand-ins. Checks:

* an opted-in contact receives a copy WITHOUT the pay link; an opted-out
  contact, a contact with no email and a contact sharing the parent's address
  receive nothing;
* another academy's contact on the same parent id never receives anything;
* contacts keyed by the canonical user id are found when the invoice carries
  an alias parent id;
* a resend, a retried parent failure and two concurrent sends never mail a
  contact twice; a failed copy is retried once on the next send; a suppressed
  address is never retried.

Skipped without a ``mongod``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.email_adapters import InvoiceEmailAdapter
from backend.v2.composition.invoice_contact_copies import build_invoice_contact_copies
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.crm.domain.family_contacts import FamilyContact
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership, User
from backend.v2.shared.tenancy import tenant_scope

A = "acad-invcopy-a"
B = "acad-invcopy-b"
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)
PARENT = "parent-1"
PARENT_ALIAS = "fb-uid-parent-1"
PARENT_EMAIL = "primary.parent@example.com"
PAY_URL = "https://checkout.stripe.test/pay/abc"


class _Sender:
    """Records sends; ``fail_once``/``suppress`` script per-address outcomes."""

    def __init__(
        self, *, fail_once: set[str] | None = None, suppress: set[str] | None = None
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_once = set(fail_once or ())
        self._suppress = set(suppress or ())

    async def send(self, **kwargs: Any) -> SendOutcome:
        await asyncio.sleep(0)  # let concurrent callers interleave
        email = kwargs["recipient"].email
        self.calls.append(kwargs)
        if email in self._suppress:
            return SendOutcome(
                ok=False, provider_message_id=None, failed_reason="suppressed", suppressed=True
            )
        if email in self._fail_once:
            self._fail_once.discard(email)
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="provider_down")
        return SendOutcome(
            ok=True, provider_message_id=f"msg-{len(self.calls)}", failed_reason=None
        )

    def to(self, email: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["recipient"].email == email]


class _Memberships:
    async def get_membership(self, academy_id: str, user_id: str) -> AcademyMembership | None:
        if user_id not in {PARENT, PARENT_ALIAS}:
            return None
        return AcademyMembership(
            membership_id=f"mem-{academy_id}",
            academy_id=academy_id,
            user_id=user_id,
            roles=("parent",),
            status="active",
        )


class _Users:
    """``get_by_id`` resolves the alias to the canonical user, like the real repo."""

    async def get_by_id(self, user_id: str) -> User | None:
        if user_id in {PARENT, PARENT_ALIAS}:
            return User(user_id=PARENT, email=PARENT_EMAIL, display_name="Primary Parent")
        return None


class _Academies:
    async def get_academy_name(self, academy_id: str) -> str | None:
        return "Test Academy"


def _contact(
    contact_id: str,
    *,
    email: str | None,
    gets_invoices: bool,
    parent_id: str = PARENT,
    gets_notices: bool = False,
) -> FamilyContact:
    return FamilyContact(
        contact_id=contact_id,
        academy_id=A,
        parent_id=parent_id,
        name=f"Contact {contact_id}",
        email=email,
        gets_notices=gets_notices,
        gets_invoices=gets_invoices,
        created_by="staff-1",
        created_at=NOW,
        updated_at=NOW,
    )


def _adapter(db: Any, sender: _Sender) -> InvoiceEmailAdapter:
    return InvoiceEmailAdapter(
        memberships=_Memberships(),  # type: ignore[arg-type]
        users=_Users(),  # type: ignore[arg-type]
        academies=_Academies(),  # type: ignore[arg-type]
        sender=sender,
        contact_copies=build_invoice_contact_copies(db, sender=sender),
    )


async def _send(
    adapter: InvoiceEmailAdapter, *, invoice_id: str = "inv-1", parent_id: str = PARENT
):
    return await adapter.send_invoice_email(
        parent_id=parent_id,
        invoice_id=invoice_id,
        period="2026-09",
        total_cents=12_000,
        balance_due_cents=12_000,
        currency="usd",
        checkout_url=PAY_URL,
    )


async def _seed(db: Any, academy: str, *contacts: FamilyContact) -> None:
    with tenant_scope(academy):
        repo = MongoFamilyContactRepository(db)
        for contact in contacts:
            await repo.add(contact)


async def test_only_opted_in_contacts_get_a_copy_without_the_pay_link(real_db: Any) -> None:
    await _seed(
        real_db,
        A,
        _contact("c-in", email="Second.Parent@Example.test", gets_invoices=True),
        _contact("c-out", email="opted.out@example.test", gets_invoices=False, gets_notices=True),
        _contact("c-same", email="Primary.Parent@example.com", gets_invoices=True),
        _contact("c-phone", email=None, gets_invoices=False),
    )
    sender = _Sender()
    with tenant_scope(A):
        message_id = await _send(_adapter(real_db, sender))

    recipients = sorted(c["recipient"].email for c in sender.calls)
    assert recipients == [PARENT_EMAIL, "second.parent@example.test"]
    assert message_id == "msg-1"  # the invoice records the parent's delivery

    (parent_call,) = sender.to(PARENT_EMAIL)
    (copy_call,) = sender.to("second.parent@example.test")
    assert PAY_URL in parent_call["body"]
    assert PAY_URL not in copy_call["body"]
    assert "payment link was sent to the family's primary email" in copy_call["body"]
    assert copy_call["subject"] == parent_call["subject"]
    assert copy_call["recipient"].user_id == "family_contact:c-in"

    row = await real_db["invoice_contact_email_sends"].find_one({"contact_id": "c-in"})
    assert row["academy_id"] == A
    assert row["status"] == "sent"
    assert row["digest_date"] == "invoice:inv-1"
    assert row["recipient_email"] == "second.parent@example.test"


async def test_another_academys_contact_never_receives_a_copy(real_db: Any) -> None:
    # Same parent id, opted in, but stored under academy B.
    await _seed(real_db, B, _contact("c-b", email="other.tenant@example.test", gets_invoices=True))
    sender = _Sender()
    with tenant_scope(A):
        await _send(_adapter(real_db, sender))

    assert [c["recipient"].email for c in sender.calls] == [PARENT_EMAIL]
    assert await real_db["invoice_contact_email_sends"].count_documents({}) == 0


async def test_contacts_are_found_when_the_invoice_carries_an_alias(real_db: Any) -> None:
    await _seed(real_db, A, _contact("c-in", email="second@example.test", gets_invoices=True))
    sender = _Sender()
    with tenant_scope(A):
        await _send(_adapter(real_db, sender), parent_id=PARENT_ALIAS)

    assert len(sender.to("second@example.test")) == 1


async def test_resend_does_not_mail_a_contact_twice(real_db: Any) -> None:
    await _seed(real_db, A, _contact("c-in", email="second@example.test", gets_invoices=True))
    sender = _Sender()
    with tenant_scope(A):
        adapter = _adapter(real_db, sender)
        await _send(adapter)
        await _send(adapter)  # admin "Re-send"
        await _send(adapter, invoice_id="inv-2")  # next invoice is a new copy

    assert len(sender.to(PARENT_EMAIL)) == 3
    copies = sender.to("second@example.test")
    assert len(copies) == 2
    assert (
        await real_db["invoice_contact_email_sends"].count_documents(
            {"academy_id": A, "recipient_email": "second@example.test"}
        )
        == 2
    )


async def test_concurrent_sends_mail_a_contact_once(real_db: Any) -> None:
    await _seed(real_db, A, _contact("c-in", email="second@example.test", gets_invoices=True))
    sender = _Sender()
    with tenant_scope(A):
        adapter = _adapter(real_db, sender)
        await asyncio.gather(*(_send(adapter) for _ in range(4)))

    assert len(sender.to(PARENT_EMAIL)) == 4
    assert len(sender.to("second@example.test")) == 1


async def test_parent_failure_sends_no_copy_and_the_retry_sends_one(real_db: Any) -> None:
    await _seed(real_db, A, _contact("c-in", email="second@example.test", gets_invoices=True))
    sender = _Sender(fail_once={PARENT_EMAIL})
    with tenant_scope(A):
        adapter = _adapter(real_db, sender)
        with pytest.raises(ValueError, match="provider_down"):
            await _send(adapter)
        assert sender.to("second@example.test") == []
        await _send(adapter)  # the monthly pass / admin retries the invoice
        await _send(adapter)

    assert len(sender.to("second@example.test")) == 1


async def test_failed_copy_is_retried_once_and_suppressed_is_terminal(real_db: Any) -> None:
    await _seed(
        real_db,
        A,
        _contact("c-flaky", email="flaky@example.test", gets_invoices=True),
        _contact("c-bounced", email="bounced@example.test", gets_invoices=True),
    )
    sender = _Sender(fail_once={"flaky@example.test"}, suppress={"bounced@example.test"})
    with tenant_scope(A):
        adapter = _adapter(real_db, sender)
        # A contact failure never fails the parent's send.
        assert await _send(adapter) == "msg-1"
        await _send(adapter)
        await _send(adapter)

    assert len(sender.to("flaky@example.test")) == 2  # failed, then delivered once
    assert len(sender.to("bounced@example.test")) == 1  # never retried
    flaky = await real_db["invoice_contact_email_sends"].find_one({"contact_id": "c-flaky"})
    bounced = await real_db["invoice_contact_email_sends"].find_one({"contact_id": "c-bounced"})
    assert flaky["status"] == "sent" and flaky["attempt_count"] == 2
    assert bounced["status"] == "failed" and bounced["retryable"] is False


async def test_the_claim_key_is_unique_per_academy_recipient_and_invoice(real_db: Any) -> None:
    from pymongo.errors import DuplicateKeyError

    doc = {
        "academy_id": A,
        "recipient_email": "second@example.test",
        "digest_date": "invoice:inv-1",
        "send_id": "s-1",
    }
    await real_db["invoice_contact_email_sends"].insert_one(dict(doc))
    with pytest.raises(DuplicateKeyError):
        await real_db["invoice_contact_email_sends"].insert_one({**doc, "send_id": "s-2"})
    # Another academy, another recipient or another invoice is a separate key.
    await real_db["invoice_contact_email_sends"].insert_one(
        {**doc, "academy_id": B, "send_id": "s-3"}
    )
    await real_db["invoice_contact_email_sends"].insert_one(
        {**doc, "recipient_email": "x@example.test", "send_id": "s-4"}
    )
    await real_db["invoice_contact_email_sends"].insert_one(
        {**doc, "digest_date": "invoice:inv-2", "send_id": "s-5"}
    )
