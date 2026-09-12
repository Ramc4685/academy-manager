"""BillEnrollmentPeriod — draft one month's tuition invoice for a single enrollment.

The monthly generator bills every enrollment at once; this is the manual
single-enrollment equivalent an admin reaches for when a family needs a month
invoiced by hand. It creates the same shape the generator creates — a draft
invoice for the enrollment's student/parent carrying one tuition line priced at
the session's monthly price, plus the enrollment's active recurring tuition
discount as its own negative line — and leaves sending to the admin.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.shared.ids import new_ulid

#: Statuses that still count as "this enrollment/period is already billed".
_LIVE_INVOICE_STATUSES = {"draft", "open", "partially_paid", "paid", "uncollectible"}

#: Enrollment statuses the generator would bill. A paused enrollment is skipped
#: by the monthly run (#651) and a cancelled/withdrawn one is no longer in the
#: class at all, so neither can be hand-billed either.
_BILLABLE_ENROLLMENT_STATUSES = {"active"}


class EnrollmentBillingTarget(BaseModel):
    """Who to bill for one enrollment, and at what monthly price."""

    model_config = {"frozen": True}

    enrollment_id: str
    academy_id: str
    student_id: str
    parent_id: str
    monthly_price_cents: int
    status: str = "active"
    #: The enrollment's active recurring tuition discount at monthly scale, already
    #: floored into ``[0, monthly_price_cents]`` and zero when no policy applies to
    #: the period — the same number the monthly generator subtracts.
    monthly_discount_cents: int = 0
    discount_description: str | None = None
    discount_id: str | None = None


class EnrollmentBillingTargetReader(Protocol):
    async def load(self, enrollment_id: str, period: str) -> EnrollmentBillingTarget | None: ...


class BillEnrollmentPeriodCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    due_date: date


def tuition_line_description(period: str) -> str:
    """The tuition line's copy, identical to the monthly generator's flat-month wording."""
    return f"Monthly tuition {period}"


class BillEnrollmentPeriod:
    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        enrollments: EnrollmentBillingTargetReader,
        add_line: AddInvoiceLine,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._enrollments = enrollments
        self._add_line = add_line
        self._now = clock

    async def execute(self, cmd: BillEnrollmentPeriodCommand) -> dict[str, Any]:
        target = await self._enrollments.load(cmd.enrollment_id, cmd.period)
        if target is None:
            raise LookupError("enrollment not found")
        if target.status not in _BILLABLE_ENROLLMENT_STATUSES:
            raise ValueError("this enrollment is not active, so it cannot be billed")
        if target.monthly_price_cents <= 0:
            # The generator skips an unpriced enrollment (skipped_no_charge) rather
            # than minting a $0 invoice; a $0 draft here could never be sent and
            # would suppress the generator's own run for the period.
            raise ValueError("this enrollment has no monthly price to bill")

        existing = await self._ledger.get_invoice_for_enrollment_period(
            cmd.enrollment_id,
            cmd.period,
            statuses=_LIVE_INVOICE_STATUSES,
        )
        if existing is not None:
            raise ValueError("this enrollment is already invoiced for that period")

        now = self._now()
        invoice_id = f"inv-{new_ulid()}"
        draft = LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=target.academy_id,
            parent_id=target.parent_id,
            student_id=target.student_id,
            enrollment_id=target.enrollment_id,
            period=cmd.period,
            status="draft",
            subtotal_cents=0,
            discount_cents=0,
            total_cents=0,
            balance_due_cents=0,
            currency="usd",
            due_date=cmd.due_date,
            created_at=now,
            updated_at=now,
        )
        idempotency_key = f"admin-bill-period-{cmd.enrollment_id}-{cmd.period}"
        created = await self._ledger.create_invoice(
            draft, lines=[], idempotency_key=idempotency_key
        )
        if created.invoice_id != invoice_id:
            # The deterministic key already has an invoice behind it. A live one means
            # a concurrent request won the race (the duplicate guard above read before
            # it landed); a void one is an invoice the admin already discarded, so this
            # attempt gets its own key rather than resurrecting it.
            if created.status != "void":
                raise ValueError("this enrollment is already invoiced for that period")
            created = await self._ledger.create_invoice(
                draft, lines=[], idempotency_key=f"{idempotency_key}-{invoice_id}"
            )

        result = await self._add_line.execute(
            AddInvoiceLineCommand(
                invoice_id=created.invoice_id,
                description=tuition_line_description(cmd.period),
                line_type="tuition",
                quantity=1,
                unit_amount_cents=target.monthly_price_cents,
            )
        )
        if target.monthly_discount_cents > 0:
            result = await self._add_line.execute(
                AddInvoiceLineCommand(
                    invoice_id=created.invoice_id,
                    description=target.discount_description or "Discount",
                    line_type="discount",
                    quantity=1,
                    unit_amount_cents=-target.monthly_discount_cents,
                    source_type="tuition_discount",
                    source_id=target.discount_id,
                )
            )
        return result.invoice.model_dump(mode="json")
