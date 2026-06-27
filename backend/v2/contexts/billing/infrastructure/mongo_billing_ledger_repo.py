"""Mongo billing ledger repository."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
    allocate_payment_to_invoice,
    recompute_totals,
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
        return LedgerInvoice(
            **{k: v for k, v in doc.items() if k not in ("_id", "idempotency_key")}
        )

    @staticmethod
    def _line_from_doc(doc: dict[str, object]) -> InvoiceLine:
        return InvoiceLine(**{k: v for k, v in doc.items() if k not in ("_id", "idempotency_key")})

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
            refunded_cents=int(doc.get("refunded_cents", 0)),
            payment_method=doc.get("payment_method"),  # type: ignore[arg-type]
            stripe_payment_intent_id=doc.get("stripe_payment_intent_id"),  # type: ignore[arg-type]
            stripe_invoice_id=doc.get("stripe_invoice_id"),  # type: ignore[arg-type]
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
            existing_invoice = self._invoice_from_doc(existing)
            repaired_lines = await self._ensure_invoice_lines(
                existing_invoice.invoice_id,
                lines=lines,
                idempotency_key=idempotency_key,
            )
            if repaired_lines:
                stored_lines = await self.get_lines_for_invoice(existing_invoice.invoice_id)
                repaired_invoice = recompute_totals(existing_invoice, stored_lines).model_copy(
                    update={"updated_at": self._clock()}
                )
                await self.save_invoice(repaired_invoice)
                return repaired_invoice
            return existing_invoice

        doc = _mongo_doc(invoice)
        doc["idempotency_key"] = idempotency_key
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})
        await self._ensure_invoice_lines(
            invoice.invoice_id,
            lines=lines,
            idempotency_key=idempotency_key,
        )
        stored = await self.get_invoice(invoice.invoice_id)
        if stored is None:
            raise ValueError("invoice insert failed")
        return stored

    async def _ensure_invoice_lines(
        self,
        invoice_id: str,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> bool:
        academy_id = current_academy_id()
        repaired = False
        for line in lines:
            line_doc = _mongo_doc(line)
            line_doc["idempotency_key"] = idempotency_key
            result = await self._db["invoice_lines"].update_one(
                {
                    "academy_id": academy_id,
                    "invoice_id": invoice_id,
                    "line_id": line.line_id,
                },
                {
                    "$setOnInsert": {
                        **{k: v for k, v in line_doc.items() if k != "academy_id"},
                        "academy_id": academy_id,
                    }
                },
                upsert=True,
            )
            if getattr(result, "upserted_id", None) is not None:
                repaired = True
        return repaired

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        doc = await self._find_one({"invoice_id": invoice_id})
        return self._invoice_from_doc(doc) if doc else None

    async def get_invoice_by_stripe_invoice_id(
        self, stripe_invoice_id: str
    ) -> LedgerInvoice | None:
        doc = await self._find_one({"stripe_invoice_id": stripe_invoice_id})
        return self._invoice_from_doc(doc) if doc else None

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        """Return the first open/draft/partially-paid invoice for a student in a period."""
        doc = await self._find_one(
            {
                "student_id": student_id,
                "period": period,
                "status": {"$in": ["open", "draft", "partially_paid"]},
            }
        )
        return self._invoice_from_doc(doc) if doc else None

    async def get_open_invoice_for_enrollment(
        self, enrollment_id: str, period: str
    ) -> LedgerInvoice | None:
        """Return the first open/draft/partially-paid invoice for an enrollment in a period."""
        doc = await self._find_one(
            {
                "enrollment_id": enrollment_id,
                "period": period,
                "status": {"$in": ["open", "draft", "partially_paid"]},
            }
        )
        return self._invoice_from_doc(doc) if doc else None

    async def get_invoice_for_enrollment_period(
        self,
        enrollment_id: str,
        period: str,
        *,
        statuses: set[str] | None = None,
    ) -> LedgerInvoice | None:
        academy_id = current_academy_id()
        query: dict[str, object] = {
            "academy_id": academy_id,
            "enrollment_id": enrollment_id,
            "period": period,
        }
        if statuses is not None:
            query["status"] = {"$in": sorted(statuses)}
        doc = await self.collection.find_one(
            query,
            sort=[("created_at", -1), ("invoice_id", -1)],
        )
        return self._invoice_from_doc(doc) if doc else None

    async def get_payment_by_stripe_payment_intent_id(
        self, stripe_payment_intent_id: str
    ) -> LedgerPayment | None:
        doc = await self.ledger_payments.find_one(
            {
                "academy_id": current_academy_id(),
                "stripe_payment_intent_id": stripe_payment_intent_id,
            }
        )
        return self._payment_from_doc(doc) if doc else None

    async def get_payment_allocation_by_idempotency_key(
        self, idempotency_key: str
    ) -> PaymentAllocation | None:
        doc = await self._db["payment_allocations"].find_one(
            {
                "academy_id": current_academy_id(),
                "idempotency_key": idempotency_key,
            }
        )
        return self._allocation_from_doc(doc) if doc else None

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
        try:
            await self.ledger_payments.insert_one(
                {**{k: v for k, v in doc.items() if k != "academy_id"}, "academy_id": academy_id}
            )
        except DuplicateKeyError:
            # Lost a concurrent race on idempotency_key — return the winner's record.
            winner = await self.ledger_payments.find_one(
                {"academy_id": academy_id, "ledger_idempotency_key": idempotency_key}
            )
            if winner is not None:
                return self._payment_from_doc(winner)
            raise  # Collision on payment_id unique index — genuine duplicate, re-raise.
        stored = await self.ledger_payments.find_one(
            {"academy_id": academy_id, "payment_id": payment.payment_id}
        )
        if stored is None:
            raise ValueError("payment insert failed")
        return self._payment_from_doc(stored)

    async def mark_payment_refunded(
        self,
        payment_id: str,
        *,
        refunded_cents: int,
        status: str,
        updated_at: datetime,
    ) -> LedgerPayment:
        academy_id = current_academy_id()
        updated = await self.ledger_payments.find_one_and_update(
            {"academy_id": academy_id, "payment_id": payment_id},
            {
                "$set": {
                    "refunded_cents": refunded_cents,
                    "status": status,
                    "updated_at": updated_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise ValueError("ledger payment not found for refund")
        return self._payment_from_doc(updated)

    async def record_payment_attempt(
        self,
        *,
        invoice_id: str,
        parent_id: str,
        amount_cents: int,
        currency: str,
        status: str,
        stripe_payment_intent_id: str | None,
        stripe_checkout_session_id: str | None,
        failure_code: str | None,
        failure_message: str | None,
        idempotency_key: str,
        created_by_event_id: str | None = None,
    ) -> dict[str, Any]:
        academy_id = current_academy_id()
        existing = await self._db["payment_attempts"].find_one(
            {"academy_id": academy_id, "idempotency_key": idempotency_key}
        )
        if existing is not None:
            return {k: v for k, v in existing.items() if k != "_id"}

        now = self._clock()
        doc = {
            "attempt_id": f"attempt-{idempotency_key}",
            "academy_id": academy_id,
            "invoice_id": invoice_id,
            "parent_id": parent_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "status": status,
            "stripe_payment_intent_id": stripe_payment_intent_id,
            "stripe_checkout_session_id": stripe_checkout_session_id,
            "failure_code": failure_code,
            "failure_message": failure_message,
            "idempotency_key": idempotency_key,
            "created_by_event_id": created_by_event_id,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await self._db["payment_attempts"].insert_one(doc)
        except DuplicateKeyError:
            winner = await self._db["payment_attempts"].find_one(
                {"academy_id": academy_id, "idempotency_key": idempotency_key}
            )
            if winner is not None:
                return {k: v for k, v in winner.items() if k != "_id"}
            raise
        return doc

    async def list_payment_attempts(self, invoice_id: str) -> list[dict[str, Any]]:
        """Return all payment attempts for one invoice, newest first (tenant-scoped)."""
        academy_id = current_academy_id()
        cursor = (
            self._db["payment_attempts"]
            .find({"academy_id": academy_id, "invoice_id": invoice_id})
            .sort("created_at", -1)
        )
        return [{k: v for k, v in doc.items() if k != "_id"} async for doc in cursor]

    async def list_open_failed_attempts(self) -> list[dict[str, Any]]:
        """One row per unpaid invoice whose latest payment attempt failed.

        Includes invoices with status ``open``/``partially_paid`` whose most
        recent attempt is ``failed`` or ``requires_action``. Paid/void invoices
        and invoices whose latest attempt succeeded are excluded. Newest failed
        attempt first.
        """
        academy_id = current_academy_id()
        rows: list[dict[str, Any]] = []
        inv_cursor = self.collection.find(
            {"academy_id": academy_id, "status": {"$in": ["open", "partially_paid"]}}
        )
        async for inv in inv_cursor:
            invoice_id = str(inv.get("invoice_id") or "")
            if not invoice_id:
                continue
            attempts = await self.list_payment_attempts(invoice_id)
            if not attempts:
                continue
            latest = attempts[0]
            if latest.get("status") not in ("failed", "requires_action"):
                continue
            rows.append(
                {
                    "invoice_id": invoice_id,
                    "parent_id": str(inv.get("parent_id") or ""),
                    "period": str(inv.get("period") or ""),
                    "total_cents": int(inv.get("total_cents", 0)),
                    "balance_due_cents": int(inv.get("balance_due_cents", 0)),
                    "currency": str(inv.get("currency", "usd")),
                    "latest_attempt_at": latest.get("created_at"),
                    "latest_decline_code": latest.get("failure_code"),
                    "attempt_count": len(attempts),
                }
            )
        rows.sort(
            key=lambda r: r["latest_attempt_at"] or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return rows

    async def list_unmatched_invoices(self) -> list[dict[str, Any]]:
        """Open/partially_paid invoices with no payment allocation yet.

        These are the legacy/migrated invoices whose historical Stripe payments
        carry no app metadata, so the reconciler can never auto-match them. They
        are the input to the human-reviewed match queue (issue #242 WI-3). An
        invoice with any ``payment_allocations`` row is considered matched and
        excluded. Newest invoice first.
        """
        academy_id = current_academy_id()
        rows: list[dict[str, Any]] = []
        inv_cursor = self.collection.find(
            {"academy_id": academy_id, "status": {"$in": ["open", "partially_paid"]}},
            sort=[("created_at", -1)],
        )
        async for inv in inv_cursor:
            invoice_id = str(inv.get("invoice_id") or "")
            if not invoice_id:
                continue
            allocation = await self._db["payment_allocations"].find_one(
                {"academy_id": academy_id, "invoice_id": invoice_id}
            )
            if allocation is not None:
                continue
            rows.append(
                {
                    "invoice_id": invoice_id,
                    "parent_id": str(inv.get("parent_id") or ""),
                    "period": str(inv.get("period") or ""),
                    "status": str(inv.get("status") or "open"),
                    "total_cents": int(inv.get("total_cents", 0)),
                    "balance_due_cents": int(inv.get("balance_due_cents", 0)),
                    "currency": str(inv.get("currency", "usd")),
                    "due_date": inv.get("due_date"),
                    "created_at": inv.get("created_at"),
                    "stripe_invoice_id": inv.get("stripe_invoice_id"),
                }
            )
        return rows

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
        try:
            await self._db["payment_allocations"].insert_one(allocation_doc)
        except DuplicateKeyError:
            existing = await self._db["payment_allocations"].find_one(
                {"academy_id": academy_id, "idempotency_key": idempotency_key}
            )
            if existing is not None:
                return await self._existing_allocation_result(existing)
            raise
        invoice_update = await self.collection.update_one(
            {
                "academy_id": academy_id,
                "invoice_id": invoice_id,
                "status": invoice_doc.get("status"),
                "balance_due_cents": invoice_doc.get("balance_due_cents"),
            },
            {
                "$set": {
                    "balance_due_cents": result.invoice.balance_due_cents,
                    "status": result.invoice.status,
                    "updated_at": result.invoice.updated_at,
                }
            },
        )
        if getattr(invoice_update, "matched_count", 0) != 1:
            await self._db["payment_allocations"].delete_one(
                {
                    "academy_id": academy_id,
                    "allocation_id": result.allocation.allocation_id,
                    "idempotency_key": idempotency_key,
                }
            )
            raise ValueError("invoice changed during allocation; retry")
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

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        academy_id = current_academy_id()
        cursor = self._db["invoice_lines"].find(
            {"academy_id": academy_id, "invoice_id": invoice_id}
        )
        return [self._line_from_doc(doc) async for doc in cursor]

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        """Upsert invoice by invoice_id."""
        academy_id = current_academy_id()
        doc = _mongo_doc(invoice)
        await self.collection.update_one(
            {"academy_id": academy_id, "invoice_id": invoice.invoice_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )
        stored = await self.get_invoice(invoice.invoice_id)
        if stored is None:
            raise ValueError("invoice save failed")
        return stored

    async def save_line(self, line: InvoiceLine) -> InvoiceLine:
        """Upsert line by line_id."""
        academy_id = current_academy_id()
        doc = _mongo_doc(line)
        await self._db["invoice_lines"].update_one(
            {"academy_id": academy_id, "line_id": line.line_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )
        return line

    async def delete_invoice_line(self, *, invoice_id: str, line_id: str) -> bool:
        """Delete one invoice line within the current tenant scope."""
        result = await self._db["invoice_lines"].delete_one(
            {
                "academy_id": current_academy_id(),
                "invoice_id": invoice_id,
                "line_id": line_id,
            }
        )
        return result.deleted_count > 0

    async def list_invoices_for_parent(
        self, parent_id: str, *, limit: int = 100
    ) -> list[LedgerInvoice]:
        cursor = self._find_many(
            {"parent_id": parent_id},
            sort=[("created_at", -1)],
            limit=limit,
        )
        return [self._invoice_from_doc(doc) async for doc in cursor]

    async def list_payments_for_parent(
        self, parent_id: str, *, limit: int = 100
    ) -> list[LedgerPayment]:
        academy_id = current_academy_id()
        cursor = self._db["ledger_payments"].find(
            {"academy_id": academy_id, "parent_id": parent_id},
            sort=[("created_at", -1)],
            limit=limit,
        )
        return [self._payment_from_doc(doc) async for doc in cursor]

    async def _existing_allocation_result(
        self, allocation_doc: dict[str, object]
    ) -> LedgerAllocationResult:
        academy_id = current_academy_id()
        allocation = self._allocation_from_doc(allocation_doc)
        invoice_doc, payment_doc = await self._repair_allocation_projection(
            allocation=allocation,
            academy_id=academy_id,
        )
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

    async def _repair_allocation_projection(
        self,
        *,
        allocation: PaymentAllocation,
        academy_id: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        invoice_doc = await self._find_one({"invoice_id": allocation.invoice_id})
        payment_doc = await self.ledger_payments.find_one(
            {"academy_id": academy_id, "payment_id": allocation.payment_id}
        )
        if invoice_doc is None or payment_doc is None:
            raise ValueError("ledger allocation points to missing invoice or payment")

        allocated_to_invoice = await self._sum_allocations(
            academy_id=academy_id,
            invoice_id=allocation.invoice_id,
        )
        invoice_total = int(invoice_doc.get("total_cents", 0))
        repaired_balance = max(0, invoice_total - allocated_to_invoice)
        current_status = str(invoice_doc.get("status", "open"))
        if current_status == "void":
            repaired_status = current_status
        elif repaired_balance == 0:
            repaired_status = "paid"
        elif allocated_to_invoice > 0:
            repaired_status = "partially_paid"
        else:
            repaired_status = "open"

        allocated_from_payment = await self._sum_allocations(
            academy_id=academy_id,
            payment_id=allocation.payment_id,
        )
        overpayment_credit = await self._sum_overpayment_credits_for_payment(
            academy_id=academy_id,
            payment_id=allocation.payment_id,
        )
        payment_amount = int(payment_doc.get("amount_cents", 0))
        repaired_unapplied = max(0, payment_amount - allocated_from_payment - overpayment_credit)

        invoice_stale = (
            int(invoice_doc.get("balance_due_cents", 0)) != repaired_balance
            or current_status != repaired_status
        )
        payment_stale = int(payment_doc.get("unapplied_amount_cents", 0)) != repaired_unapplied
        if invoice_stale or payment_stale:
            now = self._clock()
            if invoice_stale:
                await self.collection.update_one(
                    {"academy_id": academy_id, "invoice_id": allocation.invoice_id},
                    {
                        "$set": {
                            "balance_due_cents": repaired_balance,
                            "status": repaired_status,
                            "updated_at": now,
                        }
                    },
                )
            if payment_stale:
                await self.ledger_payments.update_one(
                    {"academy_id": academy_id, "payment_id": allocation.payment_id},
                    {
                        "$set": {
                            "unapplied_amount_cents": repaired_unapplied,
                            "updated_at": now,
                        }
                    },
                )

        repaired_invoice = await self._find_one({"invoice_id": allocation.invoice_id})
        repaired_payment = await self.ledger_payments.find_one(
            {"academy_id": academy_id, "payment_id": allocation.payment_id}
        )
        if repaired_invoice is None or repaired_payment is None:
            raise ValueError("ledger allocation repair failed")
        return repaired_invoice, repaired_payment

    async def _sum_allocations(
        self,
        *,
        academy_id: str,
        invoice_id: str | None = None,
        payment_id: str | None = None,
    ) -> int:
        query: dict[str, object] = {"academy_id": academy_id}
        if invoice_id is not None:
            query["invoice_id"] = invoice_id
        if payment_id is not None:
            query["payment_id"] = payment_id
        total = 0
        async for allocation_doc in self._db["payment_allocations"].find(query):
            total += int(allocation_doc.get("amount_cents", 0))
        return total

    async def _sum_overpayment_credits_for_payment(
        self,
        *,
        academy_id: str,
        payment_id: str,
    ) -> int:
        allocation_ids: list[str] = []
        async for allocation_doc in self._db["payment_allocations"].find(
            {"academy_id": academy_id, "payment_id": payment_id}
        ):
            allocation_ids.append(str(allocation_doc["allocation_id"]))
        if not allocation_ids:
            return 0

        total = 0
        async for credit_doc in self._db["account_credit_ledger"].find(
            {
                "academy_id": academy_id,
                "source_type": "OVERPAYMENT",
                "source_id": {"$in": allocation_ids},
            }
        ):
            total += int(credit_doc.get("amount_cents", 0))
        return total


def _mongo_doc(model: Any) -> dict[str, Any]:
    doc = model.model_dump(mode="python")
    if "due_date" in doc and doc["due_date"] is not None:
        due_date = doc["due_date"]
        if isinstance(due_date, date) and not isinstance(due_date, datetime):
            doc["due_date"] = datetime.combine(due_date, time.min, tzinfo=UTC)
    return doc
