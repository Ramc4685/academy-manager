"""Mongo account credit ledger repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError
from ulid import ULID

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoCreditLedgerRepository(TenantScopedRepository):
    collection_name = "account_credit_ledger"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> CreditLedgerEntry:
        return CreditLedgerEntry(
            credit_id=str(doc["credit_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            student_id=doc.get("student_id"),  # type: ignore[arg-type]
            enrollment_id=doc.get("enrollment_id"),  # type: ignore[arg-type]
            invoice_id=doc.get("invoice_id"),  # type: ignore[arg-type]
            type=doc.get("type", "MANUAL_CREDIT"),  # type: ignore[arg-type]
            status=doc.get("status", "APPROVED"),  # type: ignore[arg-type]
            amount_cents=int(doc.get("amount_cents", 0)),
            remaining_amount_cents=int(doc.get("remaining_amount_cents", 0)),
            currency=str(doc.get("currency", "usd")),
            reason=str(doc.get("reason", "")),
            calculation_snapshot_id=doc.get("calculation_snapshot_id"),  # type: ignore[arg-type]
            approved_by=doc.get("approved_by"),  # type: ignore[arg-type]
            approved_at=doc.get("approved_at"),  # type: ignore[arg-type]
            expires_at=doc.get("expires_at"),  # type: ignore[arg-type]
            stripe_credit_note_id=doc.get("stripe_credit_note_id"),  # type: ignore[arg-type]
            stripe_customer_balance_txn_id=doc.get("stripe_customer_balance_txn_id"),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
        )

    async def create(self, entry: CreditLedgerEntry) -> None:
        doc = entry.model_dump(mode="python")
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def list_for_parent(self, parent_id: str) -> list[CreditLedgerEntry]:
        cursor = self._find_many(
            {"parent_id": parent_id, "status": {"$ne": "VOIDED"}},
            sort=[("created_at", -1), ("credit_id", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def balance_for_parent(self, parent_id: str) -> int:
        now = datetime.now(timezone.utc)
        total = 0
        cursor = self._find_many(
            {
                "parent_id": parent_id,
                "status": "APPROVED",
                "remaining_amount_cents": {"$gt": 0},
                "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}],
            }
        )
        async for doc in cursor:
            total += int(doc.get("remaining_amount_cents", 0))
        return total

    async def apply_available_credits(
        self, *, parent_id: str, invoice_id: str, amount_due_cents: int
    ) -> int:
        academy_id = current_academy_id()
        now = datetime.now(timezone.utc)
        # Top-level idempotency: if any credit doc already carries this invoice
        # in its applied_invoice_ids array, we have already processed it.
        already = await self.collection.find_one(
            {"academy_id": academy_id, "applied_invoice_ids": invoice_id}
        )
        if already is not None:
            return 0
        remaining_due = amount_due_cents
        total_applied = 0
        cursor = self.collection.find(
            {
                "academy_id": academy_id,
                "parent_id": parent_id,
                "status": "APPROVED",
                "remaining_amount_cents": {"$gt": 0},
                "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}],
            }
        ).sort([("expires_at", 1), ("created_at", 1), ("credit_id", 1)])
        async for credit in cursor:
            if remaining_due <= 0:
                break
            credit_id = str(credit["credit_id"])
            available = int(credit.get("remaining_amount_cents", 0))
            amount = min(available, remaining_due)
            if amount <= 0:
                continue
            # Single atomic op: decrement remaining and record the invoice in one
            # document write.  The filter guards against double-application and
            # ensures the balance is sufficient.
            updated = await self.collection.find_one_and_update(
                {
                    "academy_id": academy_id,
                    "credit_id": credit_id,
                    "remaining_amount_cents": {"$gte": amount},
                    "status": "APPROVED",
                    "applied_invoice_ids": {"$ne": invoice_id},
                },
                {
                    "$inc": {"remaining_amount_cents": -amount},
                    "$push": {"applied_invoice_ids": invoice_id},
                    "$set": {"updated_at": now},
                },
            )
            if updated is None:
                continue
            # Audit row — best-effort; the credit doc is the source of truth.
            try:
                await self._db["credit_applications"].insert_one(
                    {
                        "academy_id": academy_id,
                        "credit_id": credit_id,
                        "invoice_id": invoice_id,
                        "parent_id": parent_id,
                        "amount_cents": amount,
                        "created_at": now,
                    }
                )
            except DuplicateKeyError:
                pass  # idempotent replay — audit already exists, credit doc is authoritative
            applied = CreditLedgerEntry(
                credit_id=str(ULID()),
                academy_id=academy_id,
                parent_id=parent_id,
                invoice_id=invoice_id,
                type="CREDIT_APPLIED",
                status="APPLIED",
                amount_cents=amount,
                remaining_amount_cents=0,
                currency=str(credit.get("currency", "usd")),
                reason=f"Applied credit {credit_id} to invoice {invoice_id}",
                calculation_snapshot_id=credit.get("calculation_snapshot_id"),
                created_at=now,
                updated_at=now,
            )
            await self.create(applied)
            total_applied += amount
            remaining_due -= amount
        return total_applied
