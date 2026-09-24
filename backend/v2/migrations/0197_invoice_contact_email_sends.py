"""Claim collection for invoice email copies to family contacts (L1b2).

``invoice_contact_email_sends`` holds one row per (academy, contact email,
invoice): the claim ``composition/invoice_contact_copies.py`` takes through
``digest_claim.claim_digest_send`` before mailing an opted-in family contact
(``family_contacts.gets_invoices``) a copy of an invoice email. The claim's
lookup, post-insert verify and re-claim all match
``(academy_id, recipient_email, digest_date)`` where ``digest_date`` is
``"invoice:<invoice_id>"``, so that is the unique key: a resend, a retried
monthly pass or two concurrent sends can never mail a contact twice.

The claim is already safe without the index (see ``digest_claim``'s docstring);
the index makes the losing insert fail fast and keeps near-duplicate rows out.
Leads with ``academy_id`` (#849); no partial filter; nothing queries it with
``$or``. New, empty collection: no data is read or changed.

Idempotent: ``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0197_invoice_contact_email_sends"

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "invoice_contact_email_sends",
        "invoice_contact_email_sends_key_unique",
        [("academy_id", 1), ("recipient_email", 1), ("digest_date", 1)],
        {"unique": True},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
