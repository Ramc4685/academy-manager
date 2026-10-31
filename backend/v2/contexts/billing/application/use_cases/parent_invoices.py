"""Parent portal invoice reads, keyed on every id the parent answers to (#932).

A parent's invoices may be stamped with any id their ``users`` document
answers to: the roster ``user_id``, the ``firebase_uid``, an old ``auth_uid``
or the users ``_id`` (People CRM spec section 1). Comparing the stored
``parent_id`` to ``claims.user_id`` exactly hid invoices stored under another
spelling of the same parent.

Aliases widen the IDENTITY side only. Every invoice read still goes through
the tenant-scoped ledger (``academy_id`` on every query), and ownership is
"the invoice's ``parent_id`` is one of THIS parent's own ids", never tenant
membership (#664).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import (
    ParentIdentityAliases,
    ParentInvoiceLedger,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice

#: Same ceiling the exact-match list always had.
PARENT_INVOICE_LIST_LIMIT = 100


async def parent_invoice_ids(identity: ParentIdentityAliases, parent_id: str) -> tuple[str, ...]:
    """The requesting id first, then the canonical id, then the rest, sorted.

    ``resolve_parent_aliases`` asks one equality question per identity field
    (never an ``$or`` across fields, #878/#894). An id no ``users`` document
    answers to keeps exactly the pre-#932 behaviour: the id itself, nothing
    wider.
    """
    if not parent_id:
        return ()
    found = (await identity.resolve_parent_aliases([parent_id])).get(parent_id)
    if found is None:
        return (parent_id,)
    return tuple(dict.fromkeys([parent_id, found.canonical_id, *sorted(found.aliases)]))


async def parent_owns_invoice(
    identity: ParentIdentityAliases, parent_id: str, invoice: LedgerInvoice
) -> bool:
    """True when ``invoice`` is stamped with one of this parent's own ids.

    The caller must have fetched ``invoice`` through the tenant-scoped ledger;
    this only widens the identity side. The pay paths use it so a parent can
    pay exactly the invoices the list and detail reads show them (#932).
    """
    return _owned_by(invoice, await parent_invoice_ids(identity, parent_id))


class ListParentInvoices:
    """``GET /parent/invoices``: the family's invoices in the request tenant."""

    def __init__(self, *, identity: ParentIdentityAliases, ledger: ParentInvoiceLedger) -> None:
        self._identity = identity
        self._ledger = ledger

    async def execute(
        self, parent_id: str, *, limit: int = PARENT_INVOICE_LIST_LIMIT
    ) -> list[LedgerInvoice]:
        ids = await parent_invoice_ids(self._identity, parent_id)
        if not ids:
            return []
        return await self._ledger.list_invoices_for_parent_aliases(ids, limit=limit)


class ParentInvoiceDetail(BaseModel):
    model_config = {"frozen": True}

    invoice: LedgerInvoice
    lines: list[InvoiceLine]


class GetParentInvoice:
    """``GET /parent/invoices/{id}``: one invoice, only if it is this family's."""

    def __init__(self, *, identity: ParentIdentityAliases, ledger: ParentInvoiceLedger) -> None:
        self._identity = identity
        self._ledger = ledger

    async def execute(self, *, parent_id: str, invoice_id: str) -> ParentInvoiceDetail | None:
        # Tenant-scoped fetch first: an invoice of another academy is simply
        # not found, whatever ids the parent answers to.
        invoice = await self._ledger.get_invoice(invoice_id)
        if invoice is None:
            return None
        if not _owned_by(invoice, await parent_invoice_ids(self._identity, parent_id)):
            return None
        lines = await self._ledger.get_lines_for_invoice(invoice_id)
        return ParentInvoiceDetail(invoice=invoice, lines=lines)


def _owned_by(invoice: LedgerInvoice, ids: Sequence[str]) -> bool:
    return bool(invoice.parent_id) and invoice.parent_id in ids
