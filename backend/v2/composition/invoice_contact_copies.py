"""Invoice email copies for opted-in family contacts (People CRM spec §4, L1b2).

A family contact with **Gets invoices (opted in)** switched on receives a copy
of each invoice email the primary parent receives. The rules:

* **Opt-in only.** Only ``family_contacts`` rows with ``gets_invoices`` true
  and an email are considered. The switch starts off and only staff turn it
  on (``crm.domain.family_contacts``).
* **Same academy only.** Contacts are read through the tenant-scoped
  ``MongoFamilyContactRepository`` (``academy_id`` comes from the tenant
  context), one ``parent_id`` equality lookup per family id (the invoice's
  stored ``parent_id`` and the parent user's canonical ``user_id``, which is
  what contacts are keyed by). Never ``$or``/``$in`` across aliases.
* **Deduped.** One copy per lowercased email; never a copy to the primary
  parent's own address.
* **A copy, never a payable link.** Payment links and autopay stay with the
  primary payer (spec §4 "Second parent"). The copy carries the amounts and the
  invoice number and says where the pay link went; it never carries the Stripe
  checkout URL.
* **At most once per invoice per recipient.** Each copy is claimed in
  ``invoice_contact_email_sends`` (migration 0197) keyed by
  ``(academy_id, recipient_email, "invoice:<invoice_id>")`` through the shared
  ``digest_claim.claim_digest_send`` (safe with or without the unique index;
  see that module's docstring for the 2026-09-02 incident). So an admin
  "Re-send", the monthly pass re-trying a failed parent send, or two
  concurrent sends never mail a contact twice. A copy that failed is retried
  on the next send of the same invoice (bounded by ``MAX_DIGEST_SEND_ATTEMPTS``);
  a suppressed address is terminal.
* **Best-effort.** The parent's delivery is what the invoice records; a contact
  copy that fails is logged and never turns the parent's send into a failure.

Lives in ``composition`` because it bridges crm (contacts) and communications
(the claim and the send port), which contexts may not import from each other.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.contexts.crm.domain.family_contacts import FamilyContact
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

log = logging.getLogger(__name__)

INVOICE_CONTACT_SENDS_COLLECTION = "invoice_contact_email_sends"

#: ``ResolvedRecipient.user_id`` prefix for a contact, matching the notice
#: audience's ``family_contact:<contact_id>`` convention.
FAMILY_CONTACT_RECIPIENT_PREFIX = "family_contact:"


def invoice_copy_key(invoice_id: str) -> str:
    """The claim namespace for one invoice (``digest_date`` in the claim row)."""
    return f"invoice:{invoice_id}"


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


class FamilyContactLister(Protocol):
    """The slice of ``MongoFamilyContactRepository`` this module needs."""

    async def list_for_family(self, parent_id: str, *, limit: int = 50) -> list[FamilyContact]: ...


class MongoInvoiceContactSendRepository(TenantScopedRepository):
    """One claim row per (academy, contact email, invoice)."""

    collection_name = INVOICE_CONTACT_SENDS_COLLECTION

    async def try_claim(
        self,
        *,
        academy_id: str,
        recipient_email: str,
        invoice_id: str,
        contact_id: str,
    ) -> dict[str, Any] | None:
        key = invoice_copy_key(invoice_id)
        doc = {
            "send_id": str(new_ulid()),
            "academy_id": academy_id,
            "recipient_email": recipient_email,
            "invoice_id": invoice_id,
            "contact_id": contact_id,
            # The field ``claim_digest_send`` keys, verifies and re-claims on.
            "digest_date": key,
            "status": str(DigestSendStatus.QUEUED),
            "provider_message_id": None,
            "failed_reason": None,
            "created_at": datetime.now(UTC),
            "attempt_count": 1,
            "retryable": True,
        }
        return await claim_digest_send(
            self.collection,
            doc=doc,
            academy_id=academy_id,
            recipient_field="recipient_email",
            recipient_id=recipient_email,
            digest_date=key,
        )

    async def mark_sent(
        self, academy_id: str, send_id: str, *, provider_message_id: str | None
    ) -> None:
        await self.collection.update_one(
            {"academy_id": academy_id, "send_id": send_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.SENT),
                    "failed_reason": None,
                    "provider_message_id": provider_message_id,
                }
            },
        )

    async def mark_failed(
        self, academy_id: str, send_id: str, reason: str, *, retryable: bool = True
    ) -> None:
        await self.collection.update_one(
            {"academy_id": academy_id, "send_id": send_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "retryable": retryable,
                }
            },
        )


class InvoiceContactCopies:
    """Sends the contact copies of one invoice email. Never raises."""

    def __init__(
        self,
        *,
        contacts: FamilyContactLister,
        sends: MongoInvoiceContactSendRepository,
        sender: EmailSendPort,
    ) -> None:
        self._contacts = contacts
        self._sends = sends
        self._sender = sender

    async def recipients(
        self, *, family_ids: Sequence[str], primary_email: str
    ) -> list[FamilyContact]:
        """Opted-in contacts with an email, one per address, primary excluded."""
        seen = {_normalize_email(primary_email)} - {""}
        chosen: list[FamilyContact] = []
        for family_id in dict.fromkeys(fid for fid in family_ids if fid):
            for contact in await self._contacts.list_for_family(family_id):
                email = _normalize_email(contact.email)
                if not contact.gets_invoices or not email or email in seen:
                    continue
                seen.add(email)
                chosen.append(contact)
        return chosen

    async def send_copies(
        self,
        *,
        family_ids: Sequence[str],
        primary_email: str,
        invoice_id: str,
        subject: str,
        body: str,
    ) -> int:
        """Send ``body`` to each opted-in contact not yet sent this invoice.

        Returns how many copies were delivered on this call.
        """
        try:
            contacts = await self.recipients(family_ids=family_ids, primary_email=primary_email)
        except Exception:
            log.exception("invoice_contact_copies_lookup_failed", extra={"invoice_id": invoice_id})
            return 0
        sent = 0
        for contact in contacts:
            try:
                if await self._send_one(contact, invoice_id=invoice_id, subject=subject, body=body):
                    sent += 1
            except Exception:
                log.exception(
                    "invoice_contact_copy_failed",
                    extra={"invoice_id": invoice_id, "contact_id": contact.contact_id},
                )
        return sent

    async def _send_one(
        self, contact: FamilyContact, *, invoice_id: str, subject: str, body: str
    ) -> bool:
        academy_id = current_academy_id()
        email = _normalize_email(contact.email)
        claim = await self._sends.try_claim(
            academy_id=academy_id,
            recipient_email=email,
            invoice_id=invoice_id,
            contact_id=contact.contact_id,
        )
        if claim is None:
            # Already sent, in flight, suppressed or out of attempts: the
            # no-duplicate-copy invariant.
            return False
        send_id = str(claim["send_id"])
        try:
            outcome = await self._sender.send(
                recipient=ResolvedRecipient(
                    user_id=f"{FAMILY_CONTACT_RECIPIENT_PREFIX}{contact.contact_id}",
                    email=email,
                    display_name=contact.name or None,
                ),
                subject=subject,
                body=body,
                category=EmailCategory.TRANSACTIONAL,
            )
        except Exception:
            await self._sends.mark_failed(academy_id, send_id, "send_exception")
            raise
        if outcome.ok:
            await self._sends.mark_sent(
                academy_id, send_id, provider_message_id=outcome.provider_message_id
            )
            return True
        if outcome.suppressed:
            await self._sends.mark_failed(academy_id, send_id, "suppressed", retryable=False)
        else:
            await self._sends.mark_failed(
                academy_id, send_id, outcome.failed_reason or "send_failed"
            )
        return False


def build_invoice_contact_copies(db: Any, *, sender: EmailSendPort) -> InvoiceContactCopies:
    """Wiring: the tenant-scoped contacts repo, the claim repo and the sender."""
    from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
        MongoFamilyContactRepository,
    )

    return InvoiceContactCopies(
        contacts=MongoFamilyContactRepository(db),
        sends=MongoInvoiceContactSendRepository(db),
        sender=sender,
    )
