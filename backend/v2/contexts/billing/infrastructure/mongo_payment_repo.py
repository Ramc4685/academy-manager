"""Mongo PaymentRepository."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from bson import ObjectId as BsonObjectId
from pymongo import ReturnDocument

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPaymentsResult,
)
from backend.v2.contexts.billing.domain.errors import (
    PaymentNotFound,
    PaymentOperationNotAllowed,
)
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    MongoMonthlyBillingGenerator,
    _session_occurrences,
)
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

# ---------------------------------------------------------------------------
# NOTE: The monthly-generation machinery (generate_monthly_payments and its
# proration/invoice-key/ledger dual-write helpers) lives in
# mongo_monthly_billing.MongoMonthlyBillingGenerator; this repo only delegates.
# The proration invocations that used to live in create_initial_quote,
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
        discounts: Any | None = None,
        ledger_repo: Any | None = None,
    ) -> None:
        super().__init__(db)
        self._clock = clock
        self._credit_ledger = credit_ledger
        self._discounts = discounts or MongoTuitionDiscountRepository(db, clock=clock)
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
            return int(doc["amount_cents"])
        if doc.get("final_amount_cents") is not None:
            return int(doc["final_amount_cents"])
        if doc.get("amount") is not None:
            return cls._money_to_cents(doc.get("amount"))
        if doc.get("final_amount") is not None:
            return cls._money_to_cents(doc.get("final_amount"))
        return 0

    @classmethod
    def _discount_cents(cls, doc: dict[str, object]) -> int:
        if doc.get("discount_cents") is not None:
            return int(doc["discount_cents"])
        return cls._money_to_cents(doc.get("discount"))

    @staticmethod
    def _refunded_cents(doc: dict[str, object]) -> int:
        if doc.get("refunded_cents") is not None:
            return int(doc["refunded_cents"])
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
            enrollment_id=doc.get("enrollment_id"),
            session_id=doc.get("session_id"),
            subscription_id=doc.get("subscription_id"),
            stripe_payment_intent_id=doc.get("stripe_payment_intent_id")
            or doc.get("stripe_payment_intent"),
            stripe_checkout_session_id=doc.get("stripe_checkout_session_id"),
            calculation_snapshot_id=doc.get("calculation_snapshot_id"),
            amount_cents=cls._amount_cents(doc),
            currency=str(doc.get("currency", "usd")),
            status=cls._normalize_status(doc.get("status")),
            refunded_cents=cls._refunded_cents(doc),
            created_at=created_at,
            updated_at=doc.get("updated_at", created_at),
        )

    async def save(self, payment: Payment) -> None:
        doc = payment.model_dump(mode="python")
        academy_id = current_academy_id()
        ledger_existing = await self._db["ledger_payments"].find_one(
            {"academy_id": academy_id, "payment_id": payment.payment_id},
            {"_id": 1},
        )
        if ledger_existing is not None:
            # Ledger-resident payment: mirror the full field set (webhook
            # lifecycle stamps stripe ids / paid_at through this branch), but
            # never clobber ledger-owned fields (unapplied_amount_cents,
            # metadata) or identity/creation stamps.
            await self._db["ledger_payments"].update_one(
                {"academy_id": academy_id, "payment_id": payment.payment_id},
                {
                    "$set": {
                        k: v
                        for k, v in doc.items()
                        if k not in ("academy_id", "payment_id", "created_at")
                    }
                },
            )
            return
        legacy_existing = await self._find_one({"payment_id": payment.payment_id})
        if legacy_existing is None:
            # Phase 5 freeze: brand-new payments are ledger-native. The legacy
            # `payments` collection no longer receives inserts — only in-place
            # updates of historical docs. The marker keeps these docs visible
            # to legacy lookups without leaking ledger-native payments
            # (autopay / pay-link) into them.
            await self._db["ledger_payments"].insert_one(
                {
                    **{k: v for k, v in doc.items() if k != "academy_id"},
                    "academy_id": academy_id,
                    "unapplied_amount_cents": 0,
                    "payment_origin": "legacy_payment",
                }
            )
            return
        await self._update_one(
            {"payment_id": payment.payment_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    def _ledger_legacy_shape_query(self, query: dict[str, Any]) -> dict[str, Any]:
        return {
            **query,
            "academy_id": current_academy_id(),
            "payment_origin": "legacy_payment",
        }

    async def _ledger_legacy_shape_docs(
        self,
        query: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self._db["ledger_payments"].find(self._ledger_legacy_shape_query(query))
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return [doc async for doc in cursor]

    async def get(self, payment_id: str) -> Payment | None:
        doc = await self._find_one(_payment_lookup(payment_id))
        if doc is None:
            doc = await self._db["ledger_payments"].find_one(
                {"academy_id": current_academy_id(), "payment_id": payment_id}
            )
        return self._to_domain(doc) if doc else None

    async def get_by_stripe_pi(self, stripe_pi: str) -> Payment | None:
        pi_query: dict[str, Any] = {
            "$or": [{"stripe_payment_intent_id": stripe_pi}, {"stripe_payment_intent": stripe_pi}]
        }
        doc = await self._find_one(pi_query)
        if doc is None:
            docs = await self._ledger_legacy_shape_docs(pi_query, limit=1)
            doc = docs[0] if docs else None
        return self._to_domain(doc) if doc else None

    async def get_by_checkout_session(self, checkout_session_id: str) -> Payment | None:
        session_query = {"stripe_checkout_session_id": checkout_session_id}
        doc = await self._find_one(session_query)
        if doc is None:
            docs = await self._ledger_legacy_shape_docs(session_query, limit=1)
            doc = docs[0] if docs else None
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
        docs.extend(
            await self._ledger_legacy_shape_docs(
                {
                    "enrollment_id": enrollment_id,
                    "status": {"$in": ["succeeded", "paid", "partially_refunded"]},
                    "calculation_snapshot_id": {"$exists": True, "$ne": None},
                },
                sort=[("paid_at", -1), ("updated_at", -1), ("created_at", -1)],
                limit=1,
            )
        )
        if docs:
            docs.sort(key=_doc_created_at_utc, reverse=True)
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
        parent_query: dict[str, Any] = {
            "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}]
        }
        cursor = self._find_many(parent_query, sort=[("created_at", -1)])
        legacy = [self._to_domain(doc) async for doc in cursor]
        return self._merged_with_ledger_shape(
            legacy, await self._ledger_legacy_shape_docs(parent_query)
        )

    async def list_all(self) -> list[Payment]:
        alive_query: dict[str, Any] = {"is_deleted": {"$ne": True}}
        cursor = self._find_many(alive_query, sort=[("created_at", -1)])
        legacy = [self._to_domain(doc) async for doc in cursor]
        return self._merged_with_ledger_shape(
            legacy, await self._ledger_legacy_shape_docs(alive_query)
        )

    def _merged_with_ledger_shape(
        self, legacy: list[Payment], ledger_docs: list[dict[str, Any]]
    ) -> list[Payment]:
        seen = {p.payment_id for p in legacy}
        merged = legacy + [
            self._to_domain(doc) for doc in ledger_docs if self._payment_id(doc) not in seen
        ]
        merged.sort(key=lambda p: p.created_at, reverse=True)
        return merged

    async def list_recent_admin(self, limit: int = 200) -> list[dict[str, object]]:
        cursor = self._find_many(
            {"is_deleted": {"$ne": True}},
            sort=[("created_at", -1), ("invoice_created_at", -1)],
            limit=limit,
        )
        docs = [doc async for doc in cursor]
        seen_ids = {self._payment_id(doc) for doc in docs}
        ledger_docs = await self._ledger_legacy_shape_docs(
            {"is_deleted": {"$ne": True}},
            sort=[("created_at", -1)],
            limit=limit,
        )
        docs.extend(doc for doc in ledger_docs if self._payment_id(doc) not in seen_ids)
        docs.sort(key=_doc_created_at_utc, reverse=True)
        docs = docs[:limit]
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

    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult:
        return await MongoMonthlyBillingGenerator(self).generate_monthly_payments(period)

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

    async def _admin_payment_doc_with_source(
        self, payment_id: str
    ) -> tuple[dict[str, object], str]:
        doc = await self._find_one(_payment_lookup(payment_id))
        if doc is not None:
            return doc, "legacy"
        ledger_doc = await self._db["ledger_payments"].find_one(
            self._ledger_legacy_shape_query({"payment_id": payment_id})
        )
        if ledger_doc is not None:
            return ledger_doc, "ledger"
        raise PaymentNotFound("no such payment", payment_id=payment_id)

    async def _admin_payment_update(
        self, payment_id: str, source: str, update: dict[str, Any]
    ) -> None:
        if source == "ledger":
            set_fields = dict(update.get("$set") or {})
            if "status" in set_fields:
                # LedgerPaymentStatus has no "partially_paid"; keep the doc
                # parseable — partial detail lives in the amount fields.
                set_fields["status"] = {"partially_paid": "pending", "paid": "succeeded"}.get(
                    str(set_fields["status"]), set_fields["status"]
                )
            await self._db["ledger_payments"].update_one(
                self._ledger_legacy_shape_query({"payment_id": payment_id}),
                {**update, "$set": set_fields} if set_fields else update,
            )
            return
        await self._update_one(_payment_lookup(payment_id), update)

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
        doc, source = await self._admin_payment_doc_with_source(payment_id)
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
        await self._admin_payment_update(
            payment_id,
            source,
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
                        student_id=doc.get("student_id"),
                        enrollment_id=doc.get("enrollment_id"),
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
        doc, source = await self._admin_payment_doc_with_source(payment_id)
        if str(doc.get("status") or "pending") != "pending":
            raise PaymentOperationNotAllowed("only pending payments can be discounted")
        if discount_cents > self._amount_cents(doc):
            raise PaymentOperationNotAllowed("discount cannot exceed payment amount")
        await self._admin_payment_update(
            payment_id,
            source,
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
        doc, source = await self._admin_payment_doc_with_source(payment_id)
        if str(doc.get("status") or "") != "succeeded":
            raise PaymentOperationNotAllowed("only paid payments can be undone")
        if self._is_stripe_linked(doc):
            raise PaymentOperationNotAllowed("Stripe-linked payments must be refunded")
        # A legacy row can front a Stripe-backed ledger payment (same payment_id,
        # see save()/get() shadow-read above) whose Stripe linkage lives only on
        # the ledger doc — check it too before allowing the undo.
        if source == "legacy":
            ledger_doc = await self._db["ledger_payments"].find_one(
                {
                    "academy_id": current_academy_id(),
                    "payment_id": self._payment_id(doc),
                }
            )
            if ledger_doc is not None and self._is_stripe_linked(ledger_doc):
                raise PaymentOperationNotAllowed("Stripe-linked payments must be refunded")
        await self._admin_payment_update(
            payment_id,
            source,
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


def _doc_created_at_utc(doc: dict[str, object]) -> datetime:
    value = doc.get("created_at") or doc.get("invoice_created_at")
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _payment_lookup(payment_id: str) -> dict[str, Any]:
    return {"$or": [{"payment_id": payment_id}, {"_id": payment_id}]}


def _safe_object_lookup(value: str) -> dict[str, Any]:
    if BsonObjectId.is_valid(value):
        return {"_id": BsonObjectId(value)}
    return {"_id": value}
