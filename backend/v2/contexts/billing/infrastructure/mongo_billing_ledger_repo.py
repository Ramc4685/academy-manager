"""Mongo billing ledger repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
    allocate_payment_to_invoice,
)
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoBillingLedgerRepository(TenantScopedRepository):
    collection_name = "invoices"
    ledger_payments_collection_name = "ledger_payments"

    def __init__(self, db: Any, *, clock=lambda: datetime.now(UTC)) -> None:
        super().__init__(db)
        self._clock = clock

    @property
    def ledger_payments(self) -> Any:
        return self._db[self.ledger_payments_collection_name]

    @staticmethod
    def _invoice_from_doc(doc: dict[str, object]) -> LedgerInvoice:
        return LedgerInvoice(**doc)

    @staticmethod
    def _line_from_doc(doc: dict[str, object]) -> InvoiceLine:
        return InvoiceLine(**doc)

    @staticmethod
    def _payment_from_doc(doc: dict[str, object]) -> LedgerPayment:
        return LedgerPayment(
            payment_id=str(doc["payment_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            amount_cents=int(doc.get("amount_cents", 0)),
            unapplied_amount_cents=int(doc.get("unapplied_amount_cents", 0)),
            currency=str(doc.get("currency", "usd")),
            status=doc.get("status", "pending"),  # type: ignore[arg-type]
            payment_method=doc.get("payment_method"),  # type: ignore[arg-type]
            stripe_payment_intent_id=doc.get("stripe_payment_intent_id"),  # type: ignore[arg-type]
            paid_at=doc.get("paid_at"),  # type: ignore[arg-type]
            recorded_by=doc.get("recorded_by"),  # type: ignore[arg-type]
            notes=doc.get("notes"),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
        )

    @staticmethod
    def _allocation_from_doc(doc: dict[str, object]) -> PaymentAllocation:
        return PaymentAllocation(**doc)

    @staticmethod
    def _credit_from_doc(doc: dict[str, object]) -> CreditLedgerEntry:
        return CreditLedgerEntry(**doc)

    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> LedgerInvoice:
        existing = await self._find_one({"idempotency_key": idempotency_key})
        if existing is not None:
            return self._invoice_from_doc(existing)

        doc = _mongo_doc(invoice)
        doc["idempotency_key"] = idempotency_key
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})
        for line in lines:
            line_doc = _mongo_doc(line)
            line_doc["idempotency_key"] = idempotency_key
            await self._db["invoice_lines"].insert_one(
                {
                    **{k: v for k, v in line_doc.items() if k != "academy_id"},
                    "academy_id": current_academy_id(),
                }
            )
        stored = await self.get_invoice(invoice.invoice_id)
        if stored is None:
            raise ValueError("invoice insert failed")
        return stored

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        doc = await self._find_one({"invoice_id": invoice_id})
        return self._invoice_from_doc(doc) if doc else None

    async def record_payment(
        self,
        payment: LedgerPayment,
        *,
        idempotency_key: str,
    ) -> LedgerPayment:
        academy_id = current_academy_id()
        existing = await self.ledger_payments.find_one(
            {"academy_id": academy_id, "ledger_idempotency_key": idempotency_key}
        )
        if existing is not None:
            return self._payment_from_doc(existing)

        doc = _mongo_doc(payment)
        doc["ledger_idempotency_key"] = idempotency_key
        await self.ledger_payments.insert_one(
            {**{k: v for k, v in doc.items() if k != "academy_id"}, "academy_id": academy_id}
        )
        stored = await self.ledger_payments.find_one(
            {"academy_id": academy_id, "payment_id": payment.payment_id}
        )
        if stored is None:
            raise ValueError("payment insert failed")
        return self._payment_from_doc(stored)

    async def allocate_payment(
        self,
        *,
        payment_id: str,
        invoice_id: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> LedgerAllocationResult:
        academy_id = current_academy_id()
        existing = await self._db["payment_allocations"].find_one(
            {"academy_id": academy_id, "idempotency_key": idempotency_key}
        )
        if existing is not None:
            return await self._existing_allocation_result(existing)

        invoice_doc = await self._find_one({"invoice_id": invoice_id})
        payment_doc = await self.ledger_payments.find_one(
            {"academy_id": academy_id, "payment_id": payment_id}
        )
        if invoice_doc is None:
            raise ValueError("invoice not found")
        if payment_doc is None:
            raise ValueError("payment not found")

        lines = [
            self._line_from_doc(doc)
            async for doc in self._db["invoice_lines"].find(
                {"academy_id": academy_id, "invoice_id": invoice_id}
            )
        ]
        result = allocate_payment_to_invoice(
            invoice=self._invoice_from_doc(invoice_doc),
            payment=self._payment_from_doc(payment_doc),
            lines=lines,
            requested_amount_cents=amount_cents,
            allocation_id=str(new_ulid()),
            now=self._clock(),
        )
        allocation_doc = _mongo_doc(result.allocation)
        allocation_doc["idempotency_key"] = idempotency_key
        await self._db["payment_allocations"].insert_one(allocation_doc)
        await self.collection.update_one(
            {"academy_id": academy_id, "invoice_id": invoice_id},
            {
                "$set": {
                    "balance_due_cents": result.invoice.balance_due_cents,
                    "status": result.invoice.status,
                    "updated_at": result.invoice.updated_at,
                }
            },
        )
        await self.ledger_payments.update_one(
            {"academy_id": academy_id, "payment_id": payment_id},
            {
                "$set": {
                    "unapplied_amount_cents": result.payment.unapplied_amount_cents,
                    "updated_at": result.payment.updated_at,
                }
            },
        )
        if result.overpayment_credit is not None:
            existing_credit = await self._db["account_credit_ledger"].find_one(
                {
                    "academy_id": academy_id,
                    "source_type": "OVERPAYMENT",
                    "source_id": result.allocation.allocation_id,
                }
            )
            if existing_credit is None:
                await self._db["account_credit_ledger"].insert_one(
                    _mongo_doc(result.overpayment_credit)
                )
        stored_allocation = await self._db["payment_allocations"].find_one(
            {"academy_id": academy_id, "idempotency_key": idempotency_key}
        )
        if stored_allocation is None:
            raise ValueError("allocation insert failed")
        return await self._existing_allocation_result(stored_allocation)

    async def list_invoices_for_academy(self, limit: int = 100) -> list[dict[str, object]]:
        academy_id = current_academy_id()
        invoices = []
        async for inv_doc in self.collection.find(
            {"academy_id": academy_id},
            sort=[("created_at", -1)],
            limit=limit,
        ):
            inv_id = inv_doc.get("invoice_id")
            if inv_id is None:
                lines = []
            else:
                lines_cursor = self._db["invoice_lines"].find(
                    {"academy_id": academy_id, "invoice_id": inv_id}
                )
                lines = [doc async for doc in lines_cursor]
            invoices.append({"invoice": inv_doc, "lines": lines})
        return invoices

    async def list_invoices_for_parent(
        self, parent_id: str, *, limit: int = 100
    ) -> list[LedgerInvoice]:
        cursor = self._find_many(
            {"parent_id": parent_id},
            sort=[("created_at", -1)],
            limit=limit,
        )
        return [self._invoice_from_doc(doc) async for doc in cursor]

    async def _existing_allocation_result(
        self, allocation_doc: dict[str, object]
    ) -> LedgerAllocationResult:
        academy_id = current_academy_id()
        allocation = self._allocation_from_doc(allocation_doc)
        invoice_doc = await self._find_one({"invoice_id": allocation.invoice_id})
        payment_doc = await self.ledger_payments.find_one(
            {"academy_id": academy_id, "payment_id": allocation.payment_id}
        )
        if invoice_doc is None or payment_doc is None:
            raise ValueError("ledger allocation points to missing invoice or payment")
        credit_doc = await self._db["account_credit_ledger"].find_one(
            {
                "academy_id": academy_id,
                "source_type": "OVERPAYMENT",
                "source_id": allocation.allocation_id,
            }
        )
        return LedgerAllocationResult(
            invoice=self._invoice_from_doc(invoice_doc),
            payment=self._payment_from_doc(payment_doc),
            allocation=allocation,
            overpayment_credit=self._credit_from_doc(credit_doc) if credit_doc else None,
        )


def _mongo_doc(model: Any) -> dict[str, Any]:
    doc = model.model_dump(mode="python")
    if "due_date" in doc and doc["due_date"] is not None:
        doc["due_date"] = doc["due_date"].isoformat()
    return doc
