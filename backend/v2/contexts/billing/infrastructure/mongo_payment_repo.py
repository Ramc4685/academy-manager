"""Mongo PaymentRepository."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId as BsonObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPaymentsResult,
)
from backend.v2.contexts.billing.domain.errors import (
    PaymentNotFound,
    PaymentOperationNotAllowed,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
    FirstMonthProrationPolicy,
    schedule_signature,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

# ---------------------------------------------------------------------------
# NOTE: This module imports FirstMonthProrationPolicy and schedule_signature
# only for the monthly-generation path (generate_monthly_payments).  The
# proration invocations that used to live in create_initial_quote,
# _amount_for_invoice, and _store_monthly_snapshot have been moved to the
# QuoteEnrollment use case and its _resolve_monthly_charge helper.
# MongoPaymentRepository now implements SessionLoader, OccurrenceCatalog, and
# SnapshotWriter via thin storage-only methods.
# ---------------------------------------------------------------------------


class MongoPaymentRepository(TenantScopedRepository):
    collection_name = "payments"

    def __init__(
        self,
        db: Any,
        *,
        clock=lambda: datetime.now(UTC),
        credit_ledger: Any | None = None,
        ledger_repo: Any | None = None,
    ) -> None:
        super().__init__(db)
        self._clock = clock
        self._credit_ledger = credit_ledger
        self._ledger_repo = ledger_repo  # MongoBillingLedgerRepository | None — Phase 2A dual-write

    @staticmethod
    def _payment_id(doc: dict[str, object]) -> str:
        return str(doc.get("payment_id") or doc.get("_id"))

    @staticmethod
    def _money_to_cents(value: object | None) -> int:
        if value is None:
            return 0
        return round(float(value) * 100)

    @classmethod
    def _amount_cents(cls, doc: dict[str, object]) -> int:
        if doc.get("amount_cents") is not None:
            return int(doc["amount_cents"])  # type: ignore[arg-type]
        if doc.get("final_amount_cents") is not None:
            return int(doc["final_amount_cents"])  # type: ignore[arg-type]
        if doc.get("amount") is not None:
            return cls._money_to_cents(doc.get("amount"))
        if doc.get("final_amount") is not None:
            return cls._money_to_cents(doc.get("final_amount"))
        return 0

    @classmethod
    def _discount_cents(cls, doc: dict[str, object]) -> int:
        if doc.get("discount_cents") is not None:
            return int(doc["discount_cents"])  # type: ignore[arg-type]
        return cls._money_to_cents(doc.get("discount"))

    @staticmethod
    def _refunded_cents(doc: dict[str, object]) -> int:
        if doc.get("refunded_cents") is not None:
            return int(doc["refunded_cents"])  # type: ignore[arg-type]
        if doc.get("refunded_amount") is not None:
            return round(float(doc["refunded_amount"]) * 100)  # type: ignore[arg-type]
        return 0

    @staticmethod
    def _is_stripe_linked(doc: dict[str, object]) -> bool:
        return any(
            bool(doc.get(field))
            for field in (
                "stripe_payment_intent_id",
                "stripe_payment_intent",
                "stripe_checkout_session_id",
                "stripe_invoice_id",
                "stripe_subscription_id",
            )
        )

    @staticmethod
    def _normalize_status(raw: object) -> str:
        # Legacy onboarding/finance writes status="paid"; v2 uses "succeeded".
        # Normalize at the boundary so the domain model only sees v2 literals.
        value = str(raw or "pending")
        if value == "paid":
            return "succeeded"
        return value

    @classmethod
    def _to_domain(cls, doc: dict[str, object]) -> Payment:
        created_at = doc.get("created_at") or doc.get("invoice_created_at") or datetime.now(UTC)
        return Payment(
            payment_id=cls._payment_id(doc),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            enrollment_id=doc.get("enrollment_id"),  # type: ignore[arg-type]
            session_id=doc.get("session_id"),  # type: ignore[arg-type]
            subscription_id=doc.get("subscription_id"),  # type: ignore[arg-type]
            stripe_payment_intent_id=doc.get("stripe_payment_intent_id")
            or doc.get("stripe_payment_intent"),  # type: ignore[arg-type]
            stripe_checkout_session_id=doc.get("stripe_checkout_session_id"),  # type: ignore[arg-type]
            calculation_snapshot_id=doc.get("calculation_snapshot_id"),  # type: ignore[arg-type]
            amount_cents=cls._amount_cents(doc),
            currency=str(doc.get("currency", "usd")),
            status=cls._normalize_status(doc.get("status")),  # type: ignore[arg-type]
            refunded_cents=cls._refunded_cents(doc),
            created_at=created_at,  # type: ignore[arg-type]
            updated_at=doc.get("updated_at", created_at),  # type: ignore[arg-type]
        )

    async def save(self, payment: Payment) -> None:
        doc = payment.model_dump(mode="python")
        ledger_existing = await self._db["ledger_payments"].find_one(
            {"academy_id": current_academy_id(), "payment_id": payment.payment_id},
            {"_id": 1},
        )
        if ledger_existing is not None:
            await self._db["ledger_payments"].update_one(
                {"academy_id": current_academy_id(), "payment_id": payment.payment_id},
                {
                    "$set": {
                        "status": payment.status,
                        "refunded_cents": payment.refunded_cents,
                        "updated_at": payment.updated_at,
                    }
                },
            )
            return
        await self._update_one(
            {"payment_id": payment.payment_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, payment_id: str) -> Payment | None:
        doc = await self._find_one(_payment_lookup(payment_id))
        if doc is None:
            doc = await self._db["ledger_payments"].find_one(
                {"academy_id": current_academy_id(), "payment_id": payment_id}
            )
        return self._to_domain(doc) if doc else None

    async def get_by_stripe_pi(self, stripe_pi: str) -> Payment | None:
        doc = await self._find_one(
            {"$or": [{"stripe_payment_intent_id": stripe_pi}, {"stripe_payment_intent": stripe_pi}]}
        )
        return self._to_domain(doc) if doc else None

    async def get_by_checkout_session(self, checkout_session_id: str) -> Payment | None:
        doc = await self._find_one({"stripe_checkout_session_id": checkout_session_id})
        return self._to_domain(doc) if doc else None

    async def latest_paid_payment_for_enrollment(self, enrollment_id: str) -> Payment | None:
        # Legacy onboarding writes status="paid"; v2 writes "succeeded". Accept both
        # so withdrawals work for either origin.
        cursor = self._find_many(
            {
                "enrollment_id": enrollment_id,
                "status": {"$in": ["succeeded", "paid", "partially_refunded"]},
                "calculation_snapshot_id": {"$exists": True, "$ne": None},
            },
            sort=[("paid_at", -1), ("updated_at", -1), ("created_at", -1), ("payment_id", -1)],
            limit=1,
        )
        docs = [doc async for doc in cursor]
        if docs:
            return self._to_domain(docs[0])
        # Fallback: legacy onboarding payments may have been written before
        # enrollment_id backfill was in place. Look them up via the enrollment's
        # session_id + parent and a stored calculation_snapshot_id, then pick the
        # latest. This keeps withdrawals working for older data without forcing
        # a manual backfill.
        enrollment_doc = await self._db["enrollments"].find_one(
            {
                "academy_id": current_academy_id(),
                "$or": [{"enrollment_id": enrollment_id}, _safe_object_lookup(enrollment_id)],
            }
        )
        if enrollment_doc is None:
            return None
        session_id = enrollment_doc.get("session_id")
        parent_id = enrollment_doc.get("parent_id") or enrollment_doc.get("parent_user_id")
        if not session_id or not parent_id:
            return None
        cursor = self._find_many(
            {
                "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
                "session_id": session_id,
                "status": {"$in": ["succeeded", "paid", "partially_refunded"]},
                "calculation_snapshot_id": {"$exists": True, "$ne": None},
            },
            sort=[("paid_at", -1), ("updated_at", -1), ("created_at", -1), ("payment_id", -1)],
            limit=1,
        )
        docs = [doc async for doc in cursor]
        return self._to_domain(docs[0]) if docs else None

    async def get_snapshot(self, snapshot_id: str) -> BillingCalculationSnapshot | None:
        doc = await self._db["billing_calculation_snapshots"].find_one(
            {"academy_id": current_academy_id(), "snapshot_id": snapshot_id}
        )
        return BillingCalculationSnapshot(**doc) if doc else None

    async def list_for_parent(self, parent_id: str) -> list[Payment]:
        cursor = self._find_many(
            {"$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}]},
            sort=[("created_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_all(self) -> list[Payment]:
        cursor = self._find_many(
            {"is_deleted": {"$ne": True}},
            sort=[("created_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_recent_admin(self, limit: int = 200) -> list[dict[str, object]]:
        cursor = self._find_many(
            {"is_deleted": {"$ne": True}},
            sort=[("created_at", -1), ("invoice_created_at", -1)],
            limit=limit,
        )
        docs = [doc async for doc in cursor]
        student_ids = sorted(
            {str(doc.get("student_id")) for doc in docs if doc.get("student_id") is not None}
        )
        students: dict[str, dict[str, object]] = {}
        if student_ids:
            oid_ids = [BsonObjectId(s) for s in student_ids if BsonObjectId.is_valid(s)]
            or_filter: list[dict[str, object]] = [{"student_id": {"$in": student_ids}}]
            if oid_ids:
                or_filter.append({"_id": {"$in": oid_ids}})
            student_cursor = self._db["students"].find(
                {"academy_id": current_academy_id(), "$or": or_filter}
            )
            async for doc in student_cursor:
                key = str(doc.get("student_id") or doc.get("_id"))
                students[key] = doc
                students[str(doc["_id"])] = doc
        parent_ids = sorted(
            {
                str(doc.get("parent_id") or doc.get("parent_user_id") or "")
                for doc in docs
                if doc.get("parent_id") or doc.get("parent_user_id")
            }
            - {""}
        )
        parents: dict[str, dict[str, object]] = {}
        if parent_ids:
            parent_cursor = self._db["users"].find(
                {
                    "academy_id": current_academy_id(),
                    "$or": [
                        {"user_id": {"$in": parent_ids}},
                        {"firebase_uid": {"$in": parent_ids}},
                    ],
                }
            )
            async for pdoc in parent_cursor:
                for key in (
                    str(pdoc.get("user_id") or ""),
                    str(pdoc.get("firebase_uid") or ""),
                ):
                    if key and key in parent_ids:
                        parents[key] = pdoc
        return [
            self._to_admin_row(
                doc,
                students.get(str(doc.get("student_id"))),
                parents.get(str(doc.get("parent_id") or doc.get("parent_user_id") or "")),
            )
            for doc in docs
        ]

    @classmethod
    def _to_admin_row(
        cls,
        doc: dict[str, object],
        student: dict[str, object] | None,
        parent_user: dict[str, object] | None = None,
    ) -> dict[str, object]:
        first = str((student or {}).get("first_name") or "").strip()
        last = str((student or {}).get("last_name") or "").strip()
        full_name = str((student or {}).get("full_name") or f"{first} {last}".strip() or "")
        created_at = doc.get("created_at") or doc.get("invoice_created_at") or datetime.now(UTC)
        amount_cents = cls._amount_cents(doc)
        discount_cents = cls._discount_cents(doc)
        parent_name = (
            str((parent_user or {}).get("display_name") or (parent_user or {}).get("name") or "")
            or None
        )
        return {
            "payment_id": cls._payment_id(doc),
            "parent_id": str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            "parent_name": parent_name,
            "student_id": doc.get("student_id"),
            "student_name": full_name or None,
            "enrollment_id": doc.get("enrollment_id"),
            "session_id": doc.get("session_id"),
            "period": doc.get("period"),
            "amount_cents": amount_cents,
            "discount_cents": discount_cents,
            "final_amount_cents": max(amount_cents - discount_cents, 0),
            "amount_received_cents": int(doc.get("amount_received_cents", 0)),
            "paid_amount_cents": int(doc.get("paid_amount_cents", 0)),
            "balance_due_cents": int(
                doc.get(
                    "balance_due_cents",
                    max(
                        max(amount_cents - discount_cents, 0)
                        - int(doc.get("paid_amount_cents", 0)),
                        0,
                    ),
                )
            ),
            "overpayment_credit_cents": int(doc.get("overpayment_credit_cents", 0)),
            "currency": str(doc.get("currency", "usd")),
            "status": str(doc.get("status", "pending")),
            "refunded_cents": cls._refunded_cents(doc),
            "invoice_number": doc.get("invoice_number"),
            "payment_method": doc.get("payment_method"),
            "stripe_linked": cls._is_stripe_linked(doc),
            "stripe_customer_id": doc.get("stripe_customer_id"),
            "stripe_checkout_session_id": doc.get("stripe_checkout_session_id"),
            "stripe_subscription_id": doc.get("stripe_subscription_id"),
            "stripe_invoice_id": doc.get("stripe_invoice_id"),
            "stripe_payment_intent_id": doc.get("stripe_payment_intent_id")
            or doc.get("stripe_payment_intent"),
            "reconciliation_status": cls._reconciliation_status(doc),
            "created_at": created_at,
        }

    @classmethod
    def _reconciliation_status(cls, doc: dict[str, object]) -> str | None:
        status = str(doc.get("status") or "")
        if status in {"pending", "partially_paid"} and cls._is_stripe_linked(doc):
            return "stripe_linked_pending"
        if status in {
            "succeeded",
            "paid",
            "partially_refunded",
            "refunded",
        } and cls._is_stripe_linked(doc):
            return "stripe_synced"
        return None

    async def _dual_write_ledger_invoice(
        self,
        *,
        ledger_repo: Any,
        payment_id: str,
        enrollment_id: str,
        parent_id: str,
        student_id: str,
        period: str,
        amount_cents: int,
        now: datetime,
    ) -> None:
        """Write a LedgerInvoice for a monthly-generated enrollment charge.

        Uses a deterministic invoice_id for idempotency so re-runs are safe.
        """
        _log = logging.getLogger(__name__)
        invoice_id = f"inv-monthly-{enrollment_id}-{period}"
        idempotency_key = f"monthly-ledger-{enrollment_id}-{period}"
        academy_id = current_academy_id()

        # Compute due_date as last day of the period month
        year, month = int(period[:4]), int(period[5:7])
        if month == 12:
            due_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            due_date = date(year, month + 1, 1) - timedelta(days=1)

        invoice = LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=academy_id,
            parent_id=parent_id,
            student_id=student_id or None,
            enrollment_id=enrollment_id,
            period=period,
            status="open",
            subtotal_cents=amount_cents,
            discount_cents=0,
            total_cents=amount_cents,
            balance_due_cents=amount_cents,
            currency="usd",
            due_date=due_date,
            created_at=now,
            updated_at=now,
        )
        line = InvoiceLine(
            line_id=f"line-monthly-{enrollment_id}-{period}",
            academy_id=academy_id,
            invoice_id=invoice_id,
            line_type="tuition",
            description=f"Monthly tuition {period}",
            quantity=1,
            unit_amount_cents=amount_cents,
            amount_cents=amount_cents,
            source_type="payment",
            source_id=payment_id,
            created_at=now,
        )
        await ledger_repo.create_invoice(invoice, lines=[line], idempotency_key=idempotency_key)

    async def _recover_orphan_monthly_invoice(
        self,
        *,
        enrollment_id: str,
        parent_id: str,
        student_id: str,
        period: str,
        gross_amount_cents: int,
        invoice_key: dict[str, object] | None,
        now: datetime,
    ) -> bool:
        if self._ledger_repo is None or invoice_key is None:
            return False
        invoice_id = f"inv-monthly-{enrollment_id}-{period}"
        existing_invoice = await self._ledger_repo.get_invoice(invoice_id)
        if existing_invoice is not None:
            return False

        payment_id = str(invoice_key.get("payment_id") or "")
        if not payment_id:
            return False

        applied_credit_cents = await self._applied_credit_cents(payment_id)
        if applied_credit_cents == 0 and self._credit_ledger is not None:
            applied_credit_cents = await self._credit_ledger.apply_available_credits(
                parent_id=parent_id,
                invoice_id=payment_id,
                amount_due_cents=gross_amount_cents,
            )
        amount_cents = max(gross_amount_cents - applied_credit_cents, 0)
        await self._dual_write_ledger_invoice(
            ledger_repo=self._ledger_repo,
            payment_id=payment_id,
            enrollment_id=enrollment_id,
            parent_id=parent_id,
            student_id=student_id,
            period=period,
            amount_cents=amount_cents,
            now=now,
        )
        return True

    async def _applied_credit_cents(self, invoice_id: str) -> int:
        total = 0
        async for doc in self._db["credit_applications"].find(
            {"academy_id": current_academy_id(), "invoice_id": invoice_id}
        ):
            total += int(doc.get("amount_cents", 0))
        return total

    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult:
        academy_id = current_academy_id()
        cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": ["active", "paused"]},
            },
            sort=[("created_at", 1), ("enrollment_id", 1)],
        )
        now = self._clock()
        created = 0
        skipped_existing = 0
        skipped_no_charge = 0
        skipped_autopay = 0
        skipped_paused = 0
        async for enrollment in cursor:
            status = str(enrollment.get("status") or "active")
            if status == "paused" or period in set(enrollment.get("skip_periods") or []):
                skipped_paused += 1
                continue
            payment_mode = str(enrollment.get("payment_mode") or "").lower()
            subscription_status = str(enrollment.get("subscription_status") or "").lower()
            if payment_mode in {"autopay", "monthly"} and subscription_status in {
                "active",
                "trialing",
                "past_due",
            }:
                skipped_autopay += 1
                continue
            billing_type = str(enrollment.get("billing_type") or "standard").lower()
            if billing_type not in {"", "standard", "monthly", "manual"}:
                skipped_no_charge += 1
                continue
            enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
            existing = await self._find_one(
                {
                    "enrollment_id": enrollment_id,
                    "period": period,
                    "is_deleted": {"$ne": True},
                }
            )
            if existing is not None:
                skipped_existing += 1
                continue
            session_id = str(enrollment.get("session_id") or "")
            student_id = str(enrollment.get("student_id") or "")
            session_doc = await self._db["sessions"].find_one(
                {"academy_id": academy_id, "session_id": session_id}
            )
            student_doc = await self._db["students"].find_one(
                {"academy_id": academy_id, "student_id": student_id}
            )
            gross_amount_cents, snapshot_id = await _resolve_charge_for_enrollment(
                repo=self,
                enrollment=enrollment,
                session_doc=session_doc or {},
                period=period,
                now=now,
            )
            if gross_amount_cents <= 0:
                skipped_no_charge += 1
                continue
            parent_id = str(
                enrollment.get("parent_id")
                or enrollment.get("parent_user_id")
                or (student_doc or {}).get("parent_id")
                or (student_doc or {}).get("parent_user_id")
                or ""
            )
            if not parent_id:
                skipped_no_charge += 1
                continue
            payment_id = str(new_ulid())
            invoice_key_id = str(new_ulid())
            try:
                await self._db["billing_invoice_keys"].insert_one(
                    {
                        "academy_id": academy_id,
                        "invoice_key_id": invoice_key_id,
                        "payment_id": payment_id,
                        "enrollment_id": enrollment_id,
                        "period": period,
                        "created_at": now,
                    }
                )
            except DuplicateKeyError:
                invoice_key = await self._db["billing_invoice_keys"].find_one(
                    {
                        "academy_id": academy_id,
                        "enrollment_id": enrollment_id,
                        "period": period,
                    }
                )
                recovered = await self._recover_orphan_monthly_invoice(
                    enrollment_id=enrollment_id,
                    parent_id=parent_id,
                    student_id=student_id,
                    period=period,
                    gross_amount_cents=gross_amount_cents,
                    invoice_key=invoice_key,
                    now=now,
                )
                if recovered:
                    created += 1
                else:
                    skipped_existing += 1
                continue
            applied_credit_cents = 0
            if self._credit_ledger is not None:
                applied_credit_cents = await self._credit_ledger.apply_available_credits(
                    parent_id=parent_id,
                    invoice_id=payment_id,
                    amount_due_cents=gross_amount_cents,
                )
            amount_cents = max(gross_amount_cents - applied_credit_cents, 0)
            # Phase 2A complete: write only to the ledger (legacy Payment write removed).
            # Phase 5 will delete MongoPaymentRepository once the prod backfill is confirmed.
            if self._ledger_repo is not None:
                await self._dual_write_ledger_invoice(
                    ledger_repo=self._ledger_repo,
                    payment_id=payment_id,
                    enrollment_id=enrollment_id,
                    parent_id=parent_id,
                    student_id=student_id,
                    period=period,
                    amount_cents=amount_cents,
                    now=now,
                )
            created += 1
        return GenerateMonthlyPaymentsResult(
            created=created,
            skipped_existing=skipped_existing,
            skipped_no_charge=skipped_no_charge,
            skipped_autopay=skipped_autopay,
            skipped_paused=skipped_paused,
        )

    # ------------------------------------------------------------------
    # SessionLoader port implementation
    # ------------------------------------------------------------------

    async def get_by_id(self, session_id: str) -> dict | None:
        """Return raw session doc for the current academy, or None."""
        academy_id = current_academy_id()
        doc = await self._db["sessions"].find_one(
            {"academy_id": academy_id, "session_id": session_id}
        )
        if doc is None:
            doc = await self._db["sessions"].find_one({"academy_id": academy_id, "_id": session_id})
        return doc

    # ------------------------------------------------------------------
    # OccurrenceCatalog port implementation
    # ------------------------------------------------------------------

    async def list_for_session(
        self,
        session_doc: dict,
        period: BillingPeriod,
    ) -> list[ClassOccurrence]:
        """Delegate to the occurrence helper (storage only, no policy)."""
        return await self._occurrences_for_session(session_doc, period)

    # ------------------------------------------------------------------
    # SnapshotWriter port implementation
    # ------------------------------------------------------------------

    async def persist_open(
        self,
        *,
        snapshot: BillingCalculationSnapshot,
        session_id: str,
        parent_id: str | None,
        student_id: str | None,
        enrollment_id: str | None,
        ttl_minutes: int,
        now: datetime,
    ) -> BillingCalculationSnapshot:
        """Stamp snapshot_id / expires_at, insert as OPEN, return stored copy."""
        academy_id = current_academy_id()
        snapshot_id = str(new_ulid())
        expires_at = now + timedelta(minutes=ttl_minutes)
        stored = snapshot.model_copy(
            update={"snapshot_id": snapshot_id, "status": "OPEN", "expires_at": expires_at}
        )
        await self._db["billing_calculation_snapshots"].insert_one(
            {
                **stored.model_dump(mode="python"),
                "academy_id": academy_id,
                "session_id": session_id,
                "student_id": student_id,
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "created_at": now,
            }
        )
        return stored

    async def consume(self, snapshot_id: str) -> BillingCalculationSnapshot | None:
        """Atomically transition OPEN → CONSUMED; return updated snapshot."""
        academy_id = current_academy_id()
        now = self._clock()
        doc = await self._db["billing_calculation_snapshots"].find_one_and_update(
            {"academy_id": academy_id, "snapshot_id": snapshot_id, "status": "OPEN"},
            {"$set": {"status": "CONSUMED", "consumed_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        return BillingCalculationSnapshot(**doc) if doc else None

    # Keep the legacy name so callers that already use it don't break.
    async def consume_quote_snapshot(self, snapshot_id: str) -> BillingCalculationSnapshot | None:
        return await self.consume(snapshot_id)

    async def persist_consumed_first_month(
        self,
        *,
        snapshot: BillingCalculationSnapshot,
        enrollment_id: str,
        session_id: str,
        student_id: str,
        now: datetime,
    ) -> str:
        """Store a CONSUMED first-month proration snapshot; return snapshot_id."""
        academy_id = current_academy_id()
        await self._db["billing_calculation_snapshots"].insert_one(
            {
                **snapshot.model_dump(mode="python"),
                "academy_id": academy_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "student_id": student_id,
            }
        )
        return str(snapshot.snapshot_id)

    async def persist_monthly_tuition(
        self,
        *,
        snapshot: BillingCalculationSnapshot,
        enrollment_id: str,
        session_id: str,
        student_id: str,
    ) -> str:
        """Store a CONSUMED monthly-tuition snapshot; return snapshot_id."""
        academy_id = current_academy_id()
        await self._db["billing_calculation_snapshots"].insert_one(
            {
                **snapshot.model_dump(mode="python"),
                "academy_id": academy_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "student_id": student_id,
            }
        )
        return str(snapshot.snapshot_id)

    async def _occurrences_for_session(
        self,
        session_doc: dict[str, object],
        period: BillingPeriod,
    ) -> list[ClassOccurrence]:
        base = _session_occurrences(session_doc, period)
        if not base:
            return []
        session_id = str(session_doc.get("session_id") or session_doc.get("_id") or "")
        override_rows = self._db["session_occurrence_overrides"].find(
            {
                "academy_id": current_academy_id(),
                "session_id": session_id,
                "occurrence_id": {"$in": [o.occurrence_id for o in base]},
            }
        )
        overrides = {str(row["occurrence_id"]): row async for row in override_rows}
        out: list[ClassOccurrence] = []
        for occurrence in base:
            override = overrides.get(occurrence.occurrence_id)
            if override is None:
                out.append(occurrence)
                continue
            status = str(override.get("status") or occurrence.status)
            is_billable = override.get("is_billable")
            if is_billable is None:
                is_billable = status in {"scheduled", "completed", "makeup"}
            out.append(
                occurrence.model_copy(
                    update={
                        "status": status,
                        "is_billable": bool(is_billable),
                    }
                )
            )
        return out

    async def mark_payment_paid(
        self,
        payment_id: str,
        *,
        payment_method: str,
        notes: str,
        amount_received_cents: int | None,
        reference_number: str | None,
        recorded_by: str | None = None,
        payment_date: date | None = None,
    ) -> None:
        doc = await self._get_admin_payment_doc(payment_id)
        if str(doc.get("status") or "pending") not in {"pending", "failed", "partially_paid"}:
            raise PaymentOperationNotAllowed("only open payments can receive manual payments")
        amount_due_cents = max(self._amount_cents(doc) - self._discount_cents(doc), 0)
        previous_received_cents = int(doc.get("amount_received_cents", 0))
        previous_credit_cents = int(doc.get("overpayment_credit_cents", 0))
        previous_paid_cents = min(previous_received_cents, amount_due_cents)
        if amount_received_cents is None:
            amount_received_cents = max(amount_due_cents - previous_paid_cents, 0)
        if amount_received_cents <= 0:
            raise PaymentOperationNotAllowed("manual payment amount must be positive")
        new_received_cents = previous_received_cents + amount_received_cents
        paid_amount_cents = min(new_received_cents, amount_due_cents)
        balance_due_cents = max(amount_due_cents - paid_amount_cents, 0)
        overpayment_credit_cents = max(new_received_cents - amount_due_cents, 0)
        new_credit_cents = max(overpayment_credit_cents - previous_credit_cents, 0)
        status = "succeeded" if balance_due_cents == 0 else "partially_paid"
        now = datetime.now(UTC)
        received_at = (
            datetime(payment_date.year, payment_date.month, payment_date.day, tzinfo=UTC)
            if payment_date is not None
            else now
        )
        await self._update_one(
            _payment_lookup(payment_id),
            {
                "$set": {
                    "status": status,
                    "payment_method": payment_method,
                    "notes": notes,
                    "reference_number": reference_number,
                    "recorded_by": recorded_by,
                    "amount_received_cents": new_received_cents,
                    "paid_amount_cents": paid_amount_cents,
                    "balance_due_cents": balance_due_cents,
                    "overpayment_credit_cents": overpayment_credit_cents,
                    "paid_at": received_at if status == "succeeded" else None,
                    "payment_date": received_at,
                    "updated_at": now,
                }
            },
        )
        if new_credit_cents > 0 and self._credit_ledger is not None:
            existing_credit = await self._db["account_credit_ledger"].find_one(
                {
                    "academy_id": current_academy_id(),
                    "source_type": "OVERPAYMENT",
                    "source_id": payment_id,
                }
            )
            if existing_credit is None:
                await self._credit_ledger.create(
                    CreditLedgerEntry(
                        credit_id=str(new_ulid()),
                        academy_id=current_academy_id(),
                        parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
                        student_id=doc.get("student_id"),  # type: ignore[arg-type]
                        enrollment_id=doc.get("enrollment_id"),  # type: ignore[arg-type]
                        invoice_id=payment_id,
                        type="MANUAL_CREDIT",
                        status="APPROVED",
                        amount_cents=new_credit_cents,
                        remaining_amount_cents=new_credit_cents,
                        currency=str(doc.get("currency", "usd")),
                        reason=f"Overpayment on payment {payment_id}",
                        source_type="OVERPAYMENT",
                        source_id=payment_id,
                        created_at=now,
                        updated_at=now,
                    )
                )

    async def apply_payment_discount(
        self, payment_id: str, discount_cents: int, *, reason: str
    ) -> None:
        doc = await self._get_admin_payment_doc(payment_id)
        if str(doc.get("status") or "pending") != "pending":
            raise PaymentOperationNotAllowed("only pending payments can be discounted")
        if discount_cents > self._amount_cents(doc):
            raise PaymentOperationNotAllowed("discount cannot exceed payment amount")
        await self._update_one(
            _payment_lookup(payment_id),
            {
                "$set": {
                    "discount_cents": discount_cents,
                    "discount": discount_cents / 100,
                    "discount_reason": reason,
                    "balance_due_cents": max(self._amount_cents(doc) - discount_cents, 0),
                    "updated_at": datetime.now(UTC),
                }
            },
        )

    async def undo_payment_paid(self, payment_id: str) -> None:
        doc = await self._get_admin_payment_doc(payment_id)
        if str(doc.get("status") or "") != "succeeded":
            raise PaymentOperationNotAllowed("only paid payments can be undone")
        if self._is_stripe_linked(doc):
            raise PaymentOperationNotAllowed("Stripe-linked payments must be refunded")
        await self._update_one(
            _payment_lookup(payment_id),
            {
                "$set": {"status": "pending", "updated_at": datetime.now(UTC)},
                "$unset": {
                    "paid_at": "",
                    "payment_date": "",
                    "payment_method": "",
                    "marked_by": "",
                    "notes": "",
                },
            },
        )

    async def _get_admin_payment_doc(self, payment_id: str) -> dict[str, object]:
        doc = await self._find_one(_payment_lookup(payment_id))
        if doc is None:
            raise PaymentNotFound("no such payment", payment_id=payment_id)
        return doc


def _payment_lookup(payment_id: str) -> dict[str, Any]:
    return {"$or": [{"payment_id": payment_id}, {"_id": payment_id}]}


def _safe_object_lookup(value: str) -> dict[str, Any]:
    if BsonObjectId.is_valid(value):
        return {"_id": BsonObjectId(value)}
    return {"_id": value}


def _session_amount_cents(doc: dict[str, object]) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return 0


def _coerce_datetime(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _session_occurrences(
    doc: dict[str, object],
    period: BillingPeriod,
) -> list[ClassOccurrence]:
    timezone_name = str(doc.get("timezone") or period.timezone or "America/Chicago")
    tz = ZoneInfo(timezone_name)
    session_id = str(doc.get("session_id") or doc.get("_id") or "")
    if doc.get("start_date") and doc.get("end_date") and doc.get("days_of_week"):
        start_date = date.fromisoformat(str(doc["start_date"]))
        end_date = date.fromisoformat(str(doc["end_date"]))
        days = {str(day)[:3].title() for day in (doc.get("days_of_week") or [])}
        start_time = time.fromisoformat(str(doc.get("start_time") or "00:00"))
        end_time = time.fromisoformat(str(doc.get("end_time") or doc.get("start_time") or "00:00"))
        current = max(start_date, period.start_at.date())
        period_last_day = date.fromordinal(period.end_at.date().toordinal() - 1)
        final = min(end_date, period_last_day)
        rows: list[ClassOccurrence] = []
        while current <= final:
            if current.strftime("%a") in days:
                local_start = datetime.combine(current, start_time, tzinfo=tz)
                local_end = datetime.combine(current, end_time, tzinfo=tz)
                rows.append(
                    ClassOccurrence(
                        occurrence_id=f"{session_id}:{current.isoformat()}:{start_time.strftime('%H:%M')}",
                        session_id=session_id,
                        start_at=local_start.astimezone(UTC),
                        end_at=local_end.astimezone(UTC),
                        status="scheduled",
                        is_billable=True,
                        timezone=timezone_name,
                    )
                )
            current = date.fromordinal(current.toordinal() + 1)
        return rows

    start_at = _coerce_datetime(doc.get("start_at"))
    end_at = _coerce_datetime(doc.get("end_at"))
    if start_at is None or end_at is None:
        return []
    local_start = start_at.astimezone(tz)
    if not (period.start_at <= local_start < period.end_at):
        return []
    return [
        ClassOccurrence(
            occurrence_id=f"{session_id}:{local_start.date().isoformat()}:{local_start.strftime('%H:%M')}",
            session_id=session_id,
            start_at=start_at,
            end_at=end_at,
            status="scheduled"
            if str(doc.get("status") or "scheduled") == "active"
            else str(doc.get("status") or "scheduled"),  # type: ignore[arg-type]
            is_billable=True,
            timezone=timezone_name,
        )
    ]


# ---------------------------------------------------------------------------
# Module-level proration helpers for generate_monthly_payments.
#
# These are free functions (NOT repo class methods) that apply
# FirstMonthProrationPolicy.  The MongoPaymentRepository class itself no
# longer performs any tuition calculation; it delegates to these functions,
# which live here purely because generate_monthly_payments is bound to the
# repo for now.  Future work can extract generate_monthly_payments into a
# proper application use case and delete these from the infra module.
# ---------------------------------------------------------------------------


async def _resolve_charge_for_enrollment(
    *,
    repo: MongoPaymentRepository,
    enrollment: dict[str, object],
    session_doc: dict[str, object],
    period: str,
    now: datetime,
) -> tuple[int, str | None]:
    """Return (gross_amount_cents, snapshot_id) for a monthly invoice row.

    This function owns all proration decisions; the repo class is a pure
    storage delegate here.
    """
    amount_cents = _session_amount_cents(session_doc)
    billing_start = _coerce_datetime(
        enrollment.get("billing_start_at")
        or enrollment.get("enrolled_at")
        or enrollment.get("created_at")
    )
    enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
    timezone_name = str(session_doc.get("timezone") or "America/Chicago")
    billing_period = BillingPeriod.from_label(period, timezone_name=timezone_name)
    occurrences = await repo._occurrences_for_session(session_doc, billing_period)

    # Not a first-month enrollment → full monthly tuition
    if billing_start is None or billing_start.strftime("%Y-%m") != period:
        snapshot = _build_monthly_tuition_snapshot(
            occurrences=occurrences,
            billing_period=billing_period,
            monthly_price_cents=amount_cents,
            now=now,
        )
        snapshot_id = await repo.persist_monthly_tuition(
            snapshot=snapshot,
            enrollment_id=enrollment_id,
            session_id=str(enrollment.get("session_id") or session_doc.get("session_id") or ""),
            student_id=str(enrollment.get("student_id") or ""),
        )
        return amount_cents, snapshot_id

    # Check if already prorated in a prior run
    academy_id = current_academy_id()
    prior_consumed = await repo._db["billing_calculation_snapshots"].find_one(
        {
            "academy_id": academy_id,
            "enrollment_id": enrollment_id,
            "billing_period_label": period,
            "status": "CONSUMED",
            "calculation_type": "FIRST_MONTH_PRORATION",
        }
    )
    if prior_consumed is not None:
        return 0, str(prior_consumed.get("snapshot_id"))

    # First-month proration
    snapshot = _build_proration_snapshot_for_first_month(
        occurrences=occurrences,
        billing_period=billing_period,
        billing_start=billing_start,
        amount_cents=amount_cents,
        now=now,
        enrollment_id=enrollment_id,
    )
    snapshot_id = await repo.persist_consumed_first_month(
        snapshot=snapshot,
        enrollment_id=enrollment_id,
        session_id=str(enrollment.get("session_id") or ""),
        student_id=str(enrollment.get("student_id") or ""),
        now=now,
    )
    return snapshot.final_amount_cents, snapshot_id


def _build_proration_snapshot_for_first_month(
    *,
    occurrences: list[ClassOccurrence],
    billing_period: BillingPeriod,
    billing_start: datetime,
    amount_cents: int,
    now: datetime,
    enrollment_id: str,
) -> BillingCalculationSnapshot:
    """Compute a CONSUMED first-month proration snapshot (no I/O)."""
    snapshot_id = str(new_ulid())
    raw = FirstMonthProrationPolicy().quote(
        monthly_price_cents=amount_cents,
        discount_cents=0,
        period=billing_period,
        occurrences=occurrences,
        billing_start_at=billing_start,
        calculated_at=now,
        calculated_by="SYSTEM",
    )
    return raw.model_copy(update={"snapshot_id": snapshot_id, "status": "CONSUMED"})


def _build_monthly_tuition_snapshot(
    *,
    occurrences: list[ClassOccurrence],
    billing_period: BillingPeriod,
    monthly_price_cents: int,
    now: datetime,
) -> BillingCalculationSnapshot:
    """Build a CONSUMED monthly-tuition snapshot (no proration, full amount)."""
    eligible = [
        occ
        for occ in sorted(occurrences, key=lambda o: o.occurrence_id)
        if FirstMonthProrationPolicy._is_eligible(occ, billing_period)
    ]
    snapshot_id = str(new_ulid())
    included = [occ.occurrence_id for occ in eligible]
    return BillingCalculationSnapshot(
        snapshot_id=snapshot_id,
        status="CONSUMED",
        calculation_type="MONTHLY_TUITION",
        monthly_price_cents=monthly_price_cents,
        discount_cents=0,
        billing_period_start=billing_period.start_at,
        billing_period_end=billing_period.end_at,
        billing_period_label=billing_period.label,
        timezone=billing_period.timezone,
        total_eligible_classes=len(eligible),
        billable_remaining_classes=len(eligible),
        proration_ratio=f"{len(eligible)}/{len(eligible)}" if eligible else "0/0",
        final_amount_cents=monthly_price_cents,
        included_occurrence_ids=included,
        excluded_occurrences={},
        schedule_signature=schedule_signature(eligible, timezone_name=billing_period.timezone),
        calculated_at=now,
        calculated_by="SYSTEM",
    )
