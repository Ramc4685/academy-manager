"""Mark one enrollment "Not billed", or start billing it again (owner only, audited).

Some children attend but are never billed: the owner's or a coach's own
children, a scholarship. "Not billed" writes the importer's existing
``billing_type`` value (``NoCharge``, :data:`NOT_BILLED_BILLING_TYPE`), so
every reader already keyed on ``billing_type`` (the monthly run, the sibling
family, the billed-students count) treats new rows exactly like imported ones.
The child stays on rosters, attendance and skills.

Going forward only. Marking a child not billed never touches an existing
invoice unless the owner also asks to void that enrollment's open, unpaid
invoices (the existing void path, one audit row per invoice). "Start billing"
restores the type the enrollment had before and skips the current month, so
the next monthly run that invoices it is next month's.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.shared.billing_type import (
    NOT_BILLED_BILLING_TYPE,
    NOT_BILLED_REASONS,
    is_not_billed,
)

logger = logging.getLogger(__name__)

#: The fields a not-billed change moves; also what the audit row records.
_AUDITED_FIELDS = ("billing_type", "not_billed_reason", "not_billed_note")


class EnrollmentNotFound(LookupError):
    pass


class NotBilledValidationError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class NotBilledStore(Protocol):
    async def get(self, enrollment_id: str) -> Mapping[str, Any] | None: ...

    async def mark_not_billed(
        self,
        enrollment_id: str,
        *,
        billing_type: str,
        reason: str,
        note: str | None,
        previous_billing_type: str | None,
        actor_id: str,
        at: datetime,
    ) -> None: ...

    async def start_billing(
        self,
        enrollment_id: str,
        *,
        billing_type: str,
        skip_period: str,
        actor_id: str,
        at: datetime,
    ) -> None: ...


class OpenInvoiceLister(Protocol):
    async def list_invoices_for_enrollment(self, enrollment_id: str) -> list[Any]: ...


class BillingMonth(Protocol):
    async def current_period(self) -> str: ...


VoidInvoice = Callable[..., Awaitable[None]]


class SetEnrollmentBillingCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    not_billed: bool
    reason: str | None = None
    note: str | None = None
    void_open_invoices: bool = False
    actor_id: str


class EnrollmentBillingResult(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    not_billed: bool
    billing_type: str
    not_billed_reason: str | None = None
    not_billed_note: str | None = None
    voided_invoice_ids: list[str] = []
    #: Open invoices left alone: money is recorded on them, or the void failed.
    kept_invoice_ids: list[str] = []
    #: "Start billing": the month the run skips (the next one invoices).
    skipped_period: str | None = None


class SetEnrollmentBilling:
    def __init__(
        self,
        *,
        store: NotBilledStore,
        invoices: OpenInvoiceLister,
        void_invoice: VoidInvoice,
        billing_month: BillingMonth,
        audit: RecordMoneySettingChange,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._invoices = invoices
        self._void = void_invoice
        self._month = billing_month
        self._audit = audit
        self._now = clock

    async def execute(
        self, academy_id: str, cmd: SetEnrollmentBillingCommand
    ) -> EnrollmentBillingResult:
        doc = await self._store.get(cmd.enrollment_id)
        if doc is None:
            raise EnrollmentNotFound(cmd.enrollment_id)
        before = {field: doc.get(field) for field in _AUDITED_FIELDS}
        now = self._now()
        skipped_period: str | None = None
        if cmd.not_billed:
            reason, note = _validated_reason(cmd.reason, cmd.note)
            await self._store.mark_not_billed(
                cmd.enrollment_id,
                billing_type=NOT_BILLED_BILLING_TYPE,
                reason=reason,
                note=note,
                # Only a billed row has a type worth restoring later; marking an
                # already not-billed row again keeps the one recorded first.
                previous_billing_type=(
                    None if is_not_billed(doc) else str(doc.get("billing_type") or "standard")
                ),
                actor_id=cmd.actor_id,
                at=now,
            )
            after = {
                "billing_type": NOT_BILLED_BILLING_TYPE,
                "not_billed_reason": reason,
                "not_billed_note": note,
            }
        else:
            if cmd.void_open_invoices:
                raise NotBilledValidationError(
                    "void_open_invoices", "only a not-billed change can void invoices"
                )
            if not is_not_billed(doc):
                return _result(doc, cmd.enrollment_id)
            restored = str(doc.get("billing_type_before_not_billed") or "standard")
            skipped_period = await self._month.current_period()
            await self._store.start_billing(
                cmd.enrollment_id,
                billing_type=restored,
                skip_period=skipped_period,
                actor_id=cmd.actor_id,
                at=now,
            )
            after = {"billing_type": restored, "not_billed_reason": None, "not_billed_note": None}

        voided: list[str] = []
        kept: list[str] = []
        if cmd.not_billed and cmd.void_open_invoices:
            voided, kept = await self._void_open_invoices(cmd, after)
        await self._audit.execute(
            academy_id=academy_id,
            action="enrollment_billing_changed",
            actor_id=cmd.actor_id,
            before={"enrollment_id": cmd.enrollment_id, **before},
            after={
                "enrollment_id": cmd.enrollment_id,
                **after,
                **({"voided_invoice_ids": voided} if voided else {}),
                **({"skipped_period": skipped_period} if skipped_period else {}),
            },
            reason=after.get("not_billed_note") or after.get("not_billed_reason"),
            parent_id=_optional_str(doc.get("parent_user_id") or doc.get("parent_id")),
        )
        return EnrollmentBillingResult(
            enrollment_id=cmd.enrollment_id,
            not_billed=cmd.not_billed,
            billing_type=str(after["billing_type"]),
            not_billed_reason=after["not_billed_reason"],
            not_billed_note=after["not_billed_note"],
            voided_invoice_ids=voided,
            kept_invoice_ids=kept,
            skipped_period=skipped_period,
        )

    async def _void_open_invoices(
        self, cmd: SetEnrollmentBillingCommand, after: Mapping[str, Any]
    ) -> tuple[list[str], list[str]]:
        voided: list[str] = []
        kept: list[str] = []
        reason = f"Not billed: {after['not_billed_note'] or after['not_billed_reason']}"
        for invoice in await self._invoices.list_invoices_for_enrollment(cmd.enrollment_id):
            # partially_paid has money on it: never voided, always reported.
            if getattr(invoice, "status", None) not in {"draft", "open", "partially_paid"}:
                continue
            # The void path refuses an invoice with money on it; report it
            # instead so the owner refunds or credits first.
            if invoice.balance_due_cents != invoice.total_cents:
                kept.append(invoice.invoice_id)
                continue
            try:
                await self._void(
                    invoice_id=invoice.invoice_id, reason=reason, actor_id=cmd.actor_id
                )
            except Exception:
                # The mark is already written; one failed void (money landed
                # since the list, a Stripe error) must not lose the audit row.
                logger.warning("not billed: void of %s failed", invoice.invoice_id, exc_info=True)
                kept.append(invoice.invoice_id)
                continue
            voided.append(invoice.invoice_id)
        return voided, kept


def _validated_reason(reason: str | None, note: str | None) -> tuple[str, str | None]:
    if reason is None or reason not in NOT_BILLED_REASONS:
        raise NotBilledValidationError("reason", "choose why this child is not billed")
    cleaned = (note or "").strip() or None
    if cleaned is not None and len(cleaned) > 500:
        raise NotBilledValidationError("note", "keep the note under 500 characters")
    if reason == "other" and cleaned is None:
        raise NotBilledValidationError("note", "add a note when the reason is Other")
    return reason, cleaned


def _result(doc: Mapping[str, Any], enrollment_id: str) -> EnrollmentBillingResult:
    return EnrollmentBillingResult(
        enrollment_id=enrollment_id,
        not_billed=is_not_billed(doc),
        billing_type=str(doc.get("billing_type") or "standard"),
        not_billed_reason=_optional_str(doc.get("not_billed_reason")),
        not_billed_note=_optional_str(doc.get("not_billed_note")),
    )


def _optional_str(value: object) -> str | None:
    return str(value) if value else None
