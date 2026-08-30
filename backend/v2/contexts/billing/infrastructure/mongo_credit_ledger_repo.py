"""Mongo account credit ledger repository."""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.domain.models import AppliedCreditState, CreditLedgerEntry
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoCreditLedgerRepository(TenantScopedRepository):
    collection_name = "account_credit_ledger"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> CreditLedgerEntry:
        return CreditLedgerEntry(
            credit_id=str(doc["credit_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            student_id=doc.get("student_id"),
            enrollment_id=doc.get("enrollment_id"),
            invoice_id=doc.get("invoice_id"),
            type=doc.get("type", "MANUAL_CREDIT"),
            status=doc.get("status", "APPROVED"),
            amount_cents=int(doc.get("amount_cents", 0)),
            remaining_amount_cents=int(doc.get("remaining_amount_cents", 0)),
            currency=str(doc.get("currency", "usd")),
            reason=str(doc.get("reason", "")),
            calculation_snapshot_id=doc.get("calculation_snapshot_id"),
            approved_by=doc.get("approved_by"),
            approved_at=doc.get("approved_at"),
            expires_at=doc.get("expires_at"),
            stripe_credit_note_id=doc.get("stripe_credit_note_id"),
            stripe_customer_balance_txn_id=doc.get("stripe_customer_balance_txn_id"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
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

    async def find_active_for_enrollment(
        self, *, enrollment_id: str, type: str
    ) -> CreditLedgerEntry | None:
        doc = await self.collection.find_one(
            {
                "academy_id": current_academy_id(),
                "enrollment_id": enrollment_id,
                "type": type,
                "status": "APPROVED",
            },
            sort=[("created_at", -1), ("credit_id", -1)],
        )
        return self._to_domain(doc) if doc else None

    async def balance_for_parent(self, parent_id: str) -> int:
        now = datetime.now(UTC)
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

    @staticmethod
    def _embedded_application_amount(credit: dict[str, object], invoice_id: str) -> int | None:
        """Amount this credit doc durably records against ``invoice_id``, if any.

        Written by :meth:`apply_available_credits` in the same atomic update as
        the balance decrement, so it survives any crash the decrement survives.
        """
        applications = credit.get("applications")
        if not isinstance(applications, list):
            return None
        total: int | None = None
        for entry in applications:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("invoice_id") or "") != invoice_id:
                continue
            total = (total or 0) + int(entry.get("amount_cents") or 0)
        return total

    @staticmethod
    def _embedded_application_applied_at(
        credit: dict[str, object], invoice_id: str
    ) -> datetime | None:
        """Earliest ``applied_at`` this credit records against ``invoice_id``."""
        applications = credit.get("applications")
        if not isinstance(applications, list):
            return None
        stamps = [
            entry["applied_at"]
            for entry in applications
            if isinstance(entry, dict)
            and str(entry.get("invoice_id") or "") == invoice_id
            and isinstance(entry.get("applied_at"), datetime)
        ]
        return min(stamps) if stamps else None

    @staticmethod
    def _applied_projection_source_id(credit_id: str, invoice_id: str) -> str:
        return f"{credit_id}:{invoice_id}"

    async def applied_credit_state(self, invoice_id: str) -> AppliedCreditState:
        """Credit already consumed by ``invoice_id``, from the source of truth.

        Resolution order per credit document:

        1. the embedded ``applications`` record (same atomic write as the
           decrement — always trustworthy);
        2. the matching ``credit_applications`` audit row (legacy documents
           written before the embedded record existed);
        3. otherwise the credit is *unresolved* — we know it was spent on this
           invoice but not how much.

        The invoice-level ``CREDIT_APPLIED`` total is used as a floor, and it
        also rescues unresolved legacy credits: if that projection accounts for
        more than the per-credit sum, the difference is the missing attribution.
        """
        academy_id = current_academy_id()

        audit_by_credit: dict[str, int] = {}
        async for row in self._db["credit_applications"].find(
            {"academy_id": academy_id, "invoice_id": invoice_id}
        ):
            audit_by_credit[str(row.get("credit_id") or "")] = int(row.get("amount_cents") or 0)

        applied_projection_cents = 0
        async for doc in self.collection.find(
            {
                "academy_id": academy_id,
                "invoice_id": invoice_id,
                "type": "CREDIT_APPLIED",
                "status": "APPLIED",
            }
        ):
            applied_projection_cents += int(doc.get("amount_cents") or 0)

        resolved_cents = 0
        unresolved: list[str] = []
        matched: set[str] = set()
        async for credit in self.collection.find(
            {
                "academy_id": academy_id,
                "$or": [
                    {"applied_invoice_ids": invoice_id},
                    {"applications.invoice_id": invoice_id},
                ],
            }
        ):
            credit_id = str(credit.get("credit_id") or "")
            matched.add(credit_id)
            amount = self._embedded_application_amount(credit, invoice_id)
            if amount is None:
                amount = audit_by_credit.get(credit_id)
            if amount is None:
                unresolved.append(credit_id)
                continue
            resolved_cents += amount

        # Audit rows whose credit document no longer carries the tag (reverse
        # drift): the money still left the parent's balance, so it counts.
        for credit_id, amount in audit_by_credit.items():
            if credit_id not in matched:
                resolved_cents += amount

        applied_cents = max(resolved_cents, applied_projection_cents)
        if unresolved and applied_projection_cents > resolved_cents:
            # The invoice-level projection covers the unattributed credits.
            unresolved = []
        return AppliedCreditState(
            applied_cents=applied_cents,
            unresolved_credit_ids=tuple(sorted(unresolved)),
        )

    async def repair_credit_projections(self, invoice_id: str) -> int:
        """Rebuild ``credit_applications`` / ``CREDIT_APPLIED`` rows lost to a crash.

        Replays the durable embedded ``applications`` records onto the two
        projections so admin views and audits agree with the credit balance we
        actually billed against. Idempotent: existing rows are left alone.
        Returns the number of rows written.
        """
        academy_id = current_academy_id()
        repaired = 0
        async for credit in self.collection.find(
            {"academy_id": academy_id, "applications.invoice_id": invoice_id}
        ):
            credit_id = str(credit.get("credit_id") or "")
            amount = self._embedded_application_amount(credit, invoice_id)
            if amount is None or amount <= 0:
                continue
            parent_id = str(credit.get("parent_id") or "")
            # The embedded record's own timestamp, so a rebuilt audit row is
            # dated when the credit was applied rather than when the credit
            # document was last touched for some other invoice.
            applied_at = (
                self._embedded_application_applied_at(credit, invoice_id)
                or credit.get("updated_at")
                or datetime.now(UTC)
            )
            audit_exists = (
                await self._db["credit_applications"].find_one(
                    {
                        "academy_id": academy_id,
                        "credit_id": credit_id,
                        "invoice_id": invoice_id,
                    }
                )
                is not None
            )
            if not audit_exists:
                try:
                    await self._db["credit_applications"].insert_one(
                        {
                            "academy_id": academy_id,
                            "credit_id": credit_id,
                            "invoice_id": invoice_id,
                            "parent_id": parent_id,
                            "amount_cents": amount,
                            "created_at": applied_at,
                            "repaired": True,
                        }
                    )
                    repaired += 1
                except DuplicateKeyError:
                    pass  # concurrent repair won the race
            if await self._applied_entry_exists(credit_id=credit_id, invoice_id=invoice_id):
                continue
            try:
                await self.create(
                    self._applied_entry(
                        credit_id=credit_id,
                        invoice_id=invoice_id,
                        parent_id=parent_id,
                        amount=amount,
                        currency=str(credit.get("currency", "usd")),
                        calculation_snapshot_id=credit.get("calculation_snapshot_id"),
                        now=applied_at,
                    )
                )
                repaired += 1
            except DuplicateKeyError:
                pass  # concurrent repair won the race
        return repaired

    async def _applied_entry_exists(self, *, credit_id: str, invoice_id: str) -> bool:
        existing = await self.collection.find_one(
            {
                "academy_id": current_academy_id(),
                "invoice_id": invoice_id,
                "type": "CREDIT_APPLIED",
                "$or": [
                    {"source_id": self._applied_projection_source_id(credit_id, invoice_id)},
                    # Entries written before source_type/source_id were stamped.
                    {"reason": f"Applied credit {credit_id} to invoice {invoice_id}"},
                ],
            }
        )
        return existing is not None

    def _applied_entry(
        self,
        *,
        credit_id: str,
        invoice_id: str,
        parent_id: str,
        amount: int,
        currency: str,
        calculation_snapshot_id: str | None,
        now: datetime,
    ) -> CreditLedgerEntry:
        return CreditLedgerEntry(
            credit_id=str(new_ulid()),
            academy_id=current_academy_id(),
            parent_id=parent_id,
            invoice_id=invoice_id,
            type="CREDIT_APPLIED",
            status="APPLIED",
            amount_cents=amount,
            remaining_amount_cents=0,
            currency=currency,
            reason=f"Applied credit {credit_id} to invoice {invoice_id}",
            source_type="CREDIT_APPLICATION",
            source_id=self._applied_projection_source_id(credit_id, invoice_id),
            calculation_snapshot_id=calculation_snapshot_id,
            created_at=now,
            updated_at=now,
        )

    async def apply_available_credits(
        self, *, parent_id: str, invoice_id: str, amount_due_cents: int
    ) -> int:
        """Apply available credit to ``invoice_id``; return the total applied.

        Idempotent and resumable (issue #233). A rerun re-reads how much this
        invoice already consumed from the credit documents themselves and
        returns that, so a caller recovering after a crash prices the invoice
        net rather than gross. Any shortfall is topped up from further credits,
        which makes a partially-applied multi-credit run resumable.
        """
        academy_id = current_academy_id()
        now = datetime.now(UTC)
        state = await self.applied_credit_state(invoice_id)
        if state.has_unresolved_drift:
            # We cannot tell how much this invoice already consumed, so we must
            # not spend more of the parent's credit against it. The caller is
            # responsible for surfacing the drift instead of billing.
            return state.applied_cents
        total_applied = state.applied_cents
        remaining_due = max(amount_due_cents - state.applied_cents, 0)
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
                    "$push": {
                        "applied_invoice_ids": invoice_id,
                        # Source of truth: the amount lands in the SAME atomic
                        # document update as the decrement, so a crash before
                        # the audit projections can no longer lose it (#233).
                        "applications": {
                            "invoice_id": invoice_id,
                            "amount_cents": amount,
                            "applied_at": now,
                        },
                    },
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
            await self.create(
                self._applied_entry(
                    credit_id=credit_id,
                    invoice_id=invoice_id,
                    parent_id=parent_id,
                    amount=amount,
                    currency=str(credit.get("currency", "usd")),
                    calculation_snapshot_id=credit.get("calculation_snapshot_id"),
                    now=now,
                )
            )
            total_applied += amount
            remaining_due -= amount
        return total_applied
