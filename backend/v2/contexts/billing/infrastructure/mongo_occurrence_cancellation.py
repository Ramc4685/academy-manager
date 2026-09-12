"""Mongo reads and the override write behind ``ApplyOccurrenceCancellation`` (#671).

Two collaborators, one file, because they only ever appear together:

``MongoOccurrenceOverrideRepository``
    Writes ``session_occurrence_overrides`` — the overlay the monthly
    generator has always READ (``MongoPaymentRepository._occurrences_for_session``)
    and that nothing has ever written. One document per
    ``(session_id, occurrence_id)``, upserted, so a retried cancel is a
    no-op rather than a duplicate.

``MongoOccurrenceCancellationReader``
    The three reads the use case needs: the session's price and zone, the
    generator's OWN synthesis of the period's classes (overrides applied —
    so this is what billing believes, not what ``session_occurrences``
    happens to hold), and the enrolled families with their recurring
    discount at monthly scale.

Every read is tenant-scoped through ``current_academy_id()`` at call time,
never a composition-time capture (#532).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.use_cases.apply_occurrence_cancellation import (
    BillableEnrollment,
    PeriodChargeBasis,
    SessionPricing,
)
from backend.v2.contexts.billing.domain.proration import ClassOccurrence
from backend.v2.contexts.billing.domain.tuition_discount import monthly_discount_cents
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import session_amount_cents
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

#: Enrollment rows a cancelled date can affect. ``paused`` is here because a
#: pause that started mid-month leaves a real invoice behind.
_AFFECTED_STATUSES = ("active", "paused")

_DEFAULT_TIMEZONE = "America/Chicago"


class MongoOccurrenceOverrideRepository(TenantScopedRepository):
    collection_name = "session_occurrence_overrides"

    async def mark_cancelled(
        self,
        *,
        session_id: str,
        occurrence_id: str,
        source_occurrence_id: str,
        reason: str,
        now: datetime,
    ) -> None:
        """Upsert the "this date is off" overlay row the generator reads.

        ``is_billable=False`` is explicit rather than inferred from the
        status: the reader falls back to a status-derived default only when
        the field is absent, and an explicit ``False`` cannot be
        misinterpreted by a future status vocabulary.
        """
        await self.collection.update_one(
            self._scoped({"session_id": session_id, "occurrence_id": occurrence_id}),
            {
                "$set": {
                    "status": "cancelled",
                    "is_billable": False,
                    "cancellation_reason": reason[:500],
                    "source_occurrence_id": source_occurrence_id,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "academy_id": current_academy_id(),
                    "session_id": session_id,
                    "occurrence_id": occurrence_id,
                    "created_at": now,
                },
            },
            upsert=True,
        )


class MongoOccurrenceCancellationReader:
    """``OccurrenceCancellationReader`` over the live billing collections."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db
        self._payments = MongoPaymentRepository(db)
        self._discounts = MongoTuitionDiscountRepository(db)

    async def session_pricing(self, session_id: str) -> SessionPricing | None:
        doc = await self._db["sessions"].find_one(
            {"academy_id": current_academy_id(), "session_id": session_id}
        )
        if doc is None:
            return None
        return SessionPricing(
            session_id=session_id,
            timezone=str(doc.get("timezone") or "") or await self._academy_timezone(),
            # The generator's own helper, never a bare ``amount_cents`` read:
            # a legacy session doc priced only in ``monthly_price_cents``
            # would otherwise credit 0 while still being billed in full (#671).
            monthly_price_cents=session_amount_cents(doc),
        )

    async def occurrences_for_period(
        self, *, session_id: str, period: str
    ) -> list[ClassOccurrence]:
        pricing = await self.session_pricing(session_id)
        if pricing is None:
            return []
        return await self._payments.occurrences_for_period(
            session_id=session_id, period=period, timezone_name=pricing.timezone
        )

    async def period_charge_basis(
        self, *, enrollment_id: str, student_id: str, session_id: str, period: str
    ) -> PeriodChargeBasis | None:
        """What the generator (or the registration checkout) actually billed
        this family for ``period`` — the divisor a credit must use (#671).

        Two lookups, in order of precision:

        1. the enrollment-keyed CONSUMED snapshot the monthly generator
           writes (``persist_monthly_tuition`` / ``persist_consumed_first_month``);
        2. the registration-checkout snapshot, which is stamped with
           ``student_id``/``session_id`` but ``enrollment_id=None`` (#506) —
           the family HAS paid the first month even though no ledger invoice
           is keyed to (enrollment, period) and the generator will never
           re-price it.

        ``None`` means nothing was priced yet; the caller falls back to
        recomputing the period's class list.
        """
        collection = self._db["billing_calculation_snapshots"]
        base = {
            "academy_id": current_academy_id(),
            "billing_period_label": period,
            "status": "CONSUMED",
        }
        doc = await collection.find_one(
            {**base, "enrollment_id": enrollment_id}, sort=[("calculated_at", -1)]
        )
        if doc is None and student_id and session_id:
            doc = await collection.find_one(
                {
                    **base,
                    "enrollment_id": None,
                    "student_id": student_id,
                    "session_id": session_id,
                    "calculation_type": "FIRST_MONTH_PRORATION",
                },
                sort=[("calculated_at", -1)],
            )
        if doc is None:
            return None
        return PeriodChargeBasis(
            calculation_type=str(doc.get("calculation_type") or ""),
            final_amount_cents=int(doc.get("final_amount_cents") or 0),
            total_eligible_classes=int(doc.get("total_eligible_classes") or 0),
            billable_remaining_classes=int(doc.get("billable_remaining_classes") or 0),
            billable_classes_denominator=(
                int(raw_denominator)
                if (raw_denominator := doc.get("billable_classes_denominator")) is not None
                else None
            ),
            included_occurrence_ids=tuple(
                str(value) for value in (doc.get("included_occurrence_ids") or [])
            ),
        )

    async def enrollments_for_session(self, session_id: str) -> list[BillableEnrollment]:
        academy_id = current_academy_id()
        cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "session_id": session_id,
                "status": {"$in": list(_AFFECTED_STATUSES)},
                "is_deleted": {"$ne": True},
            }
        )
        rows = [doc async for doc in cursor]
        if not rows:
            return []
        student_ids = sorted({str(row["student_id"]) for row in rows if row.get("student_id")})
        parents = await self._parents_by_student(academy_id, student_ids)
        price = 0
        pricing = await self.session_pricing(session_id)
        if pricing is not None:
            price = pricing.monthly_price_cents
        discounts = await self._discounts.active_by_enrollments(
            [str(row["enrollment_id"]) for row in rows]
        )

        out: list[BillableEnrollment] = []
        for row in rows:
            enrollment_id = str(row["enrollment_id"])
            student_id = str(row.get("student_id") or "")
            parent_id = parents.get(student_id)
            if not parent_id:
                # No family to credit. Recorded by the use case as a skip
                # rather than dropped here, so keep the row out entirely only
                # when we truly cannot address a credit.
                continue
            policy = discounts.get(enrollment_id)
            out.append(
                BillableEnrollment(
                    enrollment_id=enrollment_id,
                    parent_id=parent_id,
                    student_id=student_id,
                    status=str(row.get("status") or "active"),
                    billing_start_at=_coerce_datetime(
                        row.get("billing_start_at") or row.get("enrolled_at")
                    ),
                    monthly_discount_cents=(
                        monthly_discount_cents(policy, monthly_price_cents=price)
                        if policy is not None
                        else 0
                    ),
                )
            )
        return out

    async def _parents_by_student(self, academy_id: str, student_ids: list[str]) -> dict[str, str]:
        if not student_ids:
            return {}
        cursor = self._db["students"].find(
            {"academy_id": academy_id, "student_id": {"$in": student_ids}},
            {"student_id": 1, "parent_id": 1},
        )
        return {
            str(doc["student_id"]): str(doc.get("parent_id") or "")
            async for doc in cursor
            if doc.get("parent_id")
        }

    async def _academy_timezone(self) -> str:
        doc = await self._db["academies"].find_one({"academy_id": current_academy_id()})
        return str((doc or {}).get("timezone") or "") or _DEFAULT_TIMEZONE


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None
