"""Tenant-scoped parent Stripe customer storage."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.autopay_status import (
    AutopayAttemptOutcome,
    AutopayEnrollmentStatus,
    can_transition_autopay_enrollment_status,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoParentBillingCustomerRepository(TenantScopedRepository):
    collection_name = "parent_billing_customers"

    async def get_stripe_customer_id(self, *, parent_id: str) -> str | None:
        doc = await self._find_one({"parent_id": parent_id})
        if not doc:
            return None
        customer_id = doc.get("stripe_customer_id")
        return str(customer_id) if customer_id else None

    async def get_enrollment_status(self, *, parent_id: str) -> AutopayEnrollmentStatus | None:
        doc = await self._find_one({"parent_id": parent_id})
        if not doc:
            return None
        status = doc.get("autopay_enrollment_status")
        return status if status else None

    async def set_stripe_customer_id(self, *, parent_id: str, stripe_customer_id: str) -> None:
        now = datetime.now(UTC)
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": {
                    "parent_id": parent_id,
                    "stripe_customer_id": stripe_customer_id,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def set_default_payment_method(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        setup_intent_id: str,
        checkout_session_id: str | None,
        completed_at: datetime,
    ) -> None:
        now = datetime.now(UTC)
        update: dict[str, object] = {
            "parent_id": parent_id,
            "stripe_customer_id": stripe_customer_id,
            "default_payment_method_id": stripe_payment_method_id,
            "payment_method_type": payment_method_type,
            "autopay_enrollment_status": "active",
            "autopay_setup_intent_id": setup_intent_id,
            "autopay_setup_completed_at": completed_at,
            "updated_at": now,
        }
        if stripe_mandate_id:
            update["stripe_mandate_id"] = stripe_mandate_id
        if checkout_session_id:
            update["autopay_setup_checkout_session_id"] = checkout_session_id
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": update,
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def set_enrollment_status(
        self,
        *,
        parent_id: str,
        status: AutopayEnrollmentStatus,
    ) -> None:
        """Set the enrollment-lifecycle axis only. Never touches
        `last_attempt_outcome` — a charge outcome is orthogonal to whether the
        parent is enrolled in autopay.

        Illegal transitions (e.g. `paused` -> `setup_started`) are silently
        ignored rather than raised, matching the idempotent, best-effort
        nature of the other setters on this repo (webhook/worker callers
        should not crash a whole event on a stale/duplicate transition).
        """
        now = datetime.now(UTC)
        existing = await self._find_one({"parent_id": parent_id})
        current = (existing or {}).get("autopay_enrollment_status") or "not_offered"
        if not can_transition_autopay_enrollment_status(current, status):
            return
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": {
                    "parent_id": parent_id,
                    "autopay_enrollment_status": status,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def record_attempt_outcome(
        self,
        *,
        parent_id: str,
        outcome: AutopayAttemptOutcome,
        occurred_at: datetime,
        failure_code: str | None,
    ) -> None:
        """Record a projection of the latest charge attempt outcome.

        Deliberately independent of `autopay_enrollment_status` — a declined
        or errored charge does not change enrollment state. Dunning/retry
        policy (if any) reacts to this projection separately.
        """
        now = datetime.now(UTC)
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": {
                    "parent_id": parent_id,
                    "last_attempt_outcome": outcome,
                    "last_attempt_at": occurred_at,
                    "last_failure_code": failure_code,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
