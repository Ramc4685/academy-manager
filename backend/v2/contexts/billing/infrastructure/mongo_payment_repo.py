"""Mongo PaymentRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId as BsonObjectId
from ulid import new as new_ulid

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPaymentsResult,
)
from backend.v2.contexts.billing.domain.errors import (
    PaymentNotFound,
    PaymentOperationNotAllowed,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoPaymentRepository(TenantScopedRepository):
    collection_name = "payments"

    @staticmethod
    def _payment_id(doc: dict[str, object]) -> str:
        return str(doc.get("payment_id") or doc.get("_id"))

    @staticmethod
    def _money_to_cents(value: object | None) -> int:
        if value is None:
            return 0
        return int(round(float(value) * 100))

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
            return int(round(float(doc["refunded_amount"]) * 100))  # type: ignore[arg-type]
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

    @classmethod
    def _to_domain(cls, doc: dict[str, object]) -> Payment:
        created_at = (
            doc.get("created_at") or doc.get("invoice_created_at") or datetime.now(timezone.utc)
        )
        return Payment(
            payment_id=cls._payment_id(doc),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            session_id=doc.get("session_id"),  # type: ignore[arg-type]
            subscription_id=doc.get("subscription_id"),  # type: ignore[arg-type]
            stripe_payment_intent_id=doc.get("stripe_payment_intent_id")
            or doc.get("stripe_payment_intent"),  # type: ignore[arg-type]
            stripe_checkout_session_id=doc.get("stripe_checkout_session_id"),  # type: ignore[arg-type]
            amount_cents=cls._amount_cents(doc),
            currency=str(doc.get("currency", "usd")),
            status=doc.get("status", "pending"),  # type: ignore[arg-type]
            refunded_cents=cls._refunded_cents(doc),
            created_at=created_at,  # type: ignore[arg-type]
            updated_at=doc.get("updated_at", created_at),  # type: ignore[arg-type]
        )

    async def save(self, payment: Payment) -> None:
        doc = payment.model_dump(mode="python")
        await self._update_one(
            {"payment_id": payment.payment_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, payment_id: str) -> Payment | None:
        doc = await self._find_one(_payment_lookup(payment_id))
        return self._to_domain(doc) if doc else None

    async def get_by_stripe_pi(self, stripe_pi: str) -> Payment | None:
        doc = await self._find_one(
            {"$or": [{"stripe_payment_intent_id": stripe_pi}, {"stripe_payment_intent": stripe_pi}]}
        )
        return self._to_domain(doc) if doc else None

    async def get_by_checkout_session(self, checkout_session_id: str) -> Payment | None:
        doc = await self._find_one({"stripe_checkout_session_id": checkout_session_id})
        return self._to_domain(doc) if doc else None

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
            {
                str(doc.get("student_id"))
                for doc in docs
                if doc.get("student_id") is not None
            }
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
        return [self._to_admin_row(doc, students.get(str(doc.get("student_id")))) for doc in docs]

    @classmethod
    def _to_admin_row(
        cls,
        doc: dict[str, object],
        student: dict[str, object] | None,
    ) -> dict[str, object]:
        first = str((student or {}).get("first_name") or "").strip()
        last = str((student or {}).get("last_name") or "").strip()
        full_name = str((student or {}).get("full_name") or f"{first} {last}".strip() or "")
        created_at = (
            doc.get("created_at") or doc.get("invoice_created_at") or datetime.now(timezone.utc)
        )
        amount_cents = cls._amount_cents(doc)
        discount_cents = cls._discount_cents(doc)
        return {
            "payment_id": cls._payment_id(doc),
            "parent_id": str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            "student_id": doc.get("student_id"),
            "student_name": full_name or None,
            "enrollment_id": doc.get("enrollment_id"),
            "session_id": doc.get("session_id"),
            "period": doc.get("period"),
            "amount_cents": amount_cents,
            "discount_cents": discount_cents,
            "final_amount_cents": max(amount_cents - discount_cents, 0),
            "currency": str(doc.get("currency", "usd")),
            "status": str(doc.get("status", "pending")),
            "refunded_cents": cls._refunded_cents(doc),
            "invoice_number": doc.get("invoice_number"),
            "payment_method": doc.get("payment_method"),
            "stripe_linked": cls._is_stripe_linked(doc),
            "created_at": created_at,
        }

    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult:
        academy_id = current_academy_id()
        cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": ["active", "paused"]},
            },
            sort=[("created_at", 1), ("enrollment_id", 1)],
        )
        now = datetime.now(timezone.utc)
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
            amount_cents = _session_amount_cents(session_doc or {})
            if amount_cents <= 0:
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
            await self._insert_one(
                {
                    "payment_id": payment_id,
                    "parent_id": parent_id,
                    "student_id": student_id,
                    "enrollment_id": enrollment_id,
                    "session_id": session_id,
                    "period": period,
                    "amount_cents": amount_cents,
                    "discount_cents": 0,
                    "currency": "usd",
                    "status": "pending",
                    "refunded_cents": 0,
                    "invoice_number": f"INV-{period.replace('-', '')}-{payment_id[-6:]}",
                    "invoice_created_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            created += 1
        return GenerateMonthlyPaymentsResult(
            created=created,
            skipped_existing=skipped_existing,
            skipped_no_charge=skipped_no_charge,
            skipped_autopay=skipped_autopay,
            skipped_paused=skipped_paused,
        )

    async def mark_payment_paid(
        self,
        payment_id: str,
        *,
        payment_method: str,
        notes: str,
    ) -> None:
        doc = await self._get_admin_payment_doc(payment_id)
        if str(doc.get("status") or "pending") not in {"pending", "failed"}:
            raise PaymentOperationNotAllowed("only pending payments can be marked paid")
        now = datetime.now(timezone.utc)
        await self._update_one(
            _payment_lookup(payment_id),
            {
                "$set": {
                    "status": "succeeded",
                    "payment_method": payment_method,
                    "notes": notes,
                    "paid_at": now,
                    "payment_date": now,
                    "updated_at": now,
                }
            },
        )

    async def apply_payment_discount(self, payment_id: str, discount_cents: int) -> None:
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
                    "updated_at": datetime.now(timezone.utc),
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
                "$set": {"status": "pending", "updated_at": datetime.now(timezone.utc)},
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


def _session_amount_cents(doc: dict[str, object]) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price") is not None:
        return int(round(float(doc["monthly_price"]) * 100))  # type: ignore[arg-type]
    return 0
