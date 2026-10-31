"""Per-academy invoice-number prefix (Settings overhaul Phase 1 PR 2).

The prefix lives on the academy's ``billing_settings`` as
``invoice_number_prefix`` and is read by ``mint_invoice_number``. Only the
platform sets it:

* ``AssignInvoicePrefix`` runs when an academy is created and derives it from
  the slug (``ace-badminton`` -> ``ACE``), skipping prefixes other academies
  hold.
* ``SetInvoicePrefix`` is the platform-admin override
  (``/platform/academies/{id}/billing-identity``). It refuses once the academy
  has a numbered invoice, so one academy's invoice numbers never switch prefix
  midway, and it writes an append-only audit entry on every change.

The academy-side settings write (``BillingSettingsRepository.upsert``) never
persists the field. Uniqueness across academies is enforced by the
``billing_settings_invoice_number_prefix_unique`` index (migration 0206); the
pre-check here only turns the common case into a clean 409 before auditing.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import BillingSettingsRepository
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.errors import (
    InvoicePrefixAcademyNotFound,
    InvoicePrefixLocked,
    InvoicePrefixTaken,
)
from backend.v2.contexts.billing.domain.invoice_prefix import (
    invoice_prefix_candidates,
    normalize_invoice_prefix,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import tenant_scope

log = logging.getLogger(__name__)

AcademyExists = Callable[[str], Awaitable[bool]]
#: ``(academy_id) -> bool``: the academy has at least one invoice carrying an
#: ``invoice_number``, i.e. the prefix has been issued to a parent.
HasNumberedInvoice = Callable[[str], Awaitable[bool]]
#: ``(prefix, academy_id) -> bool``: another academy already holds ``prefix``.
PrefixTakenElsewhere = Callable[[str, str], Awaitable[bool]]


class BillingAuditAppender(Protocol):
    async def append(self, entry: BillingAuditEntry) -> None: ...


class InvoicePrefixResult(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    invoice_prefix: str | None
    locked: bool


class SetInvoicePrefixCommand(BaseModel):
    model_config = {"frozen": True}

    academy_id: str = Field(min_length=1)
    invoice_prefix: str
    actor_id: str = Field(min_length=1)
    reason: str | None = None


class ReadAcademyInvoicePrefix:
    """The current academy's invoice prefix, for the read-only admin Settings field."""

    def __init__(self, *, settings: BillingSettingsRepository) -> None:
        self._settings = settings

    async def execute(self) -> str | None:
        return (await self._settings.get()).invoice_number_prefix


class GetInvoicePrefix:
    def __init__(
        self,
        *,
        settings: BillingSettingsRepository,
        academy_exists: AcademyExists,
        has_numbered_invoice: HasNumberedInvoice,
    ) -> None:
        self._settings = settings
        self._academy_exists = academy_exists
        self._has_numbered_invoice = has_numbered_invoice

    async def execute(self, academy_id: str) -> InvoicePrefixResult:
        if not await self._academy_exists(academy_id):
            raise InvoicePrefixAcademyNotFound("academy not found", academy_id=academy_id)
        with tenant_scope(academy_id):
            current = await self._settings.get()
        return InvoicePrefixResult(
            academy_id=academy_id,
            invoice_prefix=current.invoice_number_prefix,
            locked=await self._has_numbered_invoice(academy_id),
        )


class SetInvoicePrefix:
    """Set one academy's invoice prefix, with an append-only audit entry.

    Idempotent: writing the current value is a no-op with no audit entry. The
    audit is written BEFORE the settings write, like ``SetApplicationFee``, so
    the prefix can never change unaudited; a write lost to a concurrent claim
    of the same prefix (the unique index) leaves an intent record, not a gap.
    """

    def __init__(
        self,
        *,
        settings: BillingSettingsRepository,
        audit: BillingAuditAppender,
        academy_exists: AcademyExists,
        has_numbered_invoice: HasNumberedInvoice,
        prefix_taken: PrefixTakenElsewhere,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._academy_exists = academy_exists
        self._has_numbered_invoice = has_numbered_invoice
        self._prefix_taken = prefix_taken
        self._now = clock

    async def execute(self, cmd: SetInvoicePrefixCommand) -> InvoicePrefixResult:
        if not await self._academy_exists(cmd.academy_id):
            raise InvoicePrefixAcademyNotFound("academy not found", academy_id=cmd.academy_id)
        prefix = normalize_invoice_prefix(cmd.invoice_prefix)
        with tenant_scope(cmd.academy_id):
            current = await self._settings.get()
            before = current.invoice_number_prefix
            if before == prefix:
                return InvoicePrefixResult(
                    academy_id=cmd.academy_id,
                    invoice_prefix=prefix,
                    locked=await self._has_numbered_invoice(cmd.academy_id),
                )
            if await self._has_numbered_invoice(cmd.academy_id):
                raise InvoicePrefixLocked(
                    "the academy has issued numbered invoices; its prefix can no longer change",
                    academy_id=cmd.academy_id,
                    invoice_prefix=before,
                )
            if await self._prefix_taken(prefix, cmd.academy_id):
                raise InvoicePrefixTaken(
                    "another academy already uses this invoice prefix", invoice_prefix=prefix
                )
            await self._audit.append(
                BillingAuditEntry(
                    audit_id=f"baud-{new_ulid()}",
                    academy_id=cmd.academy_id,
                    action="invoice_prefix_changed",
                    actor_id=cmd.actor_id,
                    at=self._now(),
                    reason=cmd.reason,
                    before={"invoice_number_prefix": before},
                    after={"invoice_number_prefix": prefix},
                )
            )
            await self._settings.set_invoice_number_prefix(prefix)
        log.info(
            "invoice_prefix: academy=%s prefix %s -> %s by actor=%s",
            cmd.academy_id,
            before,
            prefix,
            cmd.actor_id,
        )
        return InvoicePrefixResult(academy_id=cmd.academy_id, invoice_prefix=prefix, locked=False)


class AssignInvoicePrefix:
    """Give a newly created academy its invoice prefix, derived from its slug.

    Idempotent: an academy that already has a prefix keeps it (re-running a
    bootstrap never renames BLNO). Candidates are tried in order and the
    unique index decides, so two academies created at once cannot both claim
    ``ACE``: the loser moves on to ``ACE2``.
    """

    def __init__(self, *, settings: BillingSettingsRepository) -> None:
        self._settings = settings

    async def execute(self, *, academy_id: str, slug: str) -> str:
        with tenant_scope(academy_id):
            current = await self._settings.get()
            if current.invoice_number_prefix:
                return current.invoice_number_prefix
            for candidate in invoice_prefix_candidates(slug):
                try:
                    await self._settings.set_invoice_number_prefix(candidate)
                except InvoicePrefixTaken:
                    continue
                log.info("invoice_prefix_assigned academy=%s prefix=%s", academy_id, candidate)
                return candidate
        raise InvoicePrefixTaken("no free invoice prefix for slug", slug=slug)
