"""Mongo StudentBillingEnrollmentRepository.

This aggregate is the single per-enrollment source of truth for autopay status
(``autopay_enrollment_status`` + the ``last_attempt_outcome`` projection). Each
child's enrollment carries its own state so pausing one child never affects a
sibling. ``set_autopay_enrollment_status`` is the ONE guarded write path — the
webhook/legacy-convergence port and pause/resume all route through it so no
caller can silently diverge from the transition rules.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.domain.autopay_status import (
    AutopayAttemptOutcome,
    AutopayEnrollmentStatus,
    can_transition_autopay_enrollment_status,
)
from backend.v2.contexts.billing.domain.session_type import StudentBillingEnrollment
from backend.v2.shared.tenancy import TenantScopedRepository

log = logging.getLogger(__name__)


class MongoStudentBillingEnrollmentRepository(TenantScopedRepository):
    collection_name = "student_billing_enrollments"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> StudentBillingEnrollment:
        return StudentBillingEnrollment(
            enrollment_id=str(doc["enrollment_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            parent_id=str(doc["parent_id"]),
            session_type_id=str(doc["session_type_id"]),
            stripe_subscription_id=doc.get("stripe_subscription_id"),  # type: ignore[arg-type]
            billing_start_date=doc["billing_start_date"],  # type: ignore[arg-type]
            status=doc.get("status", "active"),  # type: ignore[arg-type]
            autopay_enrollment_status=doc.get("autopay_enrollment_status", "not_offered"),  # type: ignore[arg-type]
            last_attempt_outcome=doc.get("last_attempt_outcome"),  # type: ignore[arg-type]
            last_attempt_at=doc.get("last_attempt_at"),  # type: ignore[arg-type]
            last_failure_code=doc.get("last_failure_code"),  # type: ignore[arg-type]
            override_price_cents=doc.get("override_price_cents"),  # type: ignore[arg-type]
            enrolled_at=doc["enrolled_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
        )

    async def save(self, enrollment: StudentBillingEnrollment) -> None:
        doc = enrollment.model_dump(mode="python")
        await self._update_one(
            {"enrollment_id": enrollment.enrollment_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, enrollment_id: str) -> StudentBillingEnrollment | None:
        doc = await self._find_one({"enrollment_id": enrollment_id})
        return self._to_domain(doc) if doc else None

    async def list_for_student(self, student_id: str) -> list[StudentBillingEnrollment]:
        cursor = self._find_many({"student_id": student_id}, sort=[("enrolled_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_parent(self, parent_id: str) -> list[StudentBillingEnrollment]:
        cursor = self._find_many({"parent_id": parent_id}, sort=[("enrolled_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def get_by_stripe_subscription(
        self, stripe_subscription_id: str
    ) -> StudentBillingEnrollment | None:
        doc = await self._find_one({"stripe_subscription_id": stripe_subscription_id})
        return self._to_domain(doc) if doc else None

    async def get_autopay_enrollment_status(
        self, *, enrollment_id: str
    ) -> AutopayEnrollmentStatus | None:
        doc = await self._find_one({"enrollment_id": enrollment_id})
        if not doc:
            return None
        status = doc.get("autopay_enrollment_status")
        return status if status else None  # type: ignore[return-value]

    async def set_autopay_enrollment_status(
        self,
        *,
        enrollment_id: str,
        status: AutopayEnrollmentStatus,
        session: Any | None = None,
    ) -> bool:
        """The ONE guarded write for the per-enrollment autopay-status axis.

        Returns True if the transition was applied, False if it was a rejected
        (illegal) transition. Rejected transitions are a no-op — never raise, so
        idempotent webhook/worker replay is safe — but they log at WARNING so a
        silently-un-paused (or un-resumed) autopay is observable. Callers should
        surface a warning of their own when this returns False (see BLOCKING #2).

        Never touches `last_attempt_outcome`: a charge outcome is orthogonal to
        whether the enrollment is enrolled in autopay.
        """
        existing = await self._find_one({"enrollment_id": enrollment_id}, session=session)
        if existing is None:
            log.warning(
                "autopay status transition skipped: enrollment not found "
                "enrollment_id=%s target=%s",
                enrollment_id,
                status,
            )
            return False
        current = existing.get("autopay_enrollment_status") or "not_offered"
        if not can_transition_autopay_enrollment_status(current, status):  # type: ignore[arg-type]
            log.warning(
                "autopay status transition rejected: illegal current=%s -> target=%s "
                "enrollment_id=%s",
                current,
                status,
                enrollment_id,
            )
            return False
        filter_: dict[str, Any] = {"enrollment_id": enrollment_id}
        if current == "not_offered":
            filter_["$or"] = [
                {"autopay_enrollment_status": "not_offered"},
                {"autopay_enrollment_status": {"$exists": False}},
                {"autopay_enrollment_status": None},
                {"autopay_enrollment_status": ""},
            ]
        else:
            filter_["autopay_enrollment_status"] = current
        result = await self._update_one(
            filter_,
            {"$set": {"autopay_enrollment_status": status, "updated_at": datetime.now(UTC)}},
            session=session,
        )
        applied = getattr(result, "matched_count", 0) == 1
        if not applied:
            log.warning(
                "autopay status transition skipped: enrollment changed during update "
                "current=%s target=%s enrollment_id=%s",
                current,
                status,
                enrollment_id,
            )
        return applied

    async def mark_autopay_active_from_setup(
        self, *, enrollment_id: str, session: Any | None = None
    ) -> bool:
        """Transition an enrollment to ``active`` after a successful autopay
        setup completion, walking the legal intermediate states as needed.

        Setup completion can land from several starting points:
        ``not_offered``/``offered``/``setup_started`` on first setup, or
        ``disabled`` on a re-setup after a prior teardown. Since the transition
        table forbids jumping straight from ``not_offered``/``disabled`` to
        ``active``, this walks ``-> offered -> setup_started -> active`` through
        the guarded path so the invariant is never bypassed. Idempotent: an
        already-``active`` enrollment is a no-op that returns True.

        Returns True if the enrollment ends up ``active``, False if it could
        not be resolved (e.g. enrollment not found).
        """
        walk_to_active: dict[str, list[AutopayEnrollmentStatus]] = {
            "not_offered": ["offered", "setup_started", "active"],
            "offered": ["setup_started", "active"],
            "setup_started": ["active"],
            "paused": ["active"],
            "disabled": ["offered", "setup_started", "active"],
            "active": [],
        }
        existing = await self._find_one({"enrollment_id": enrollment_id}, session=session)
        if existing is None:
            log.warning(
                "autopay setup completion skipped: enrollment not found enrollment_id=%s",
                enrollment_id,
            )
            return False
        current = existing.get("autopay_enrollment_status") or "not_offered"
        for step in walk_to_active.get(current, ["offered", "setup_started", "active"]):
            applied = await self.set_autopay_enrollment_status(
                enrollment_id=enrollment_id, status=step, session=session
            )
            if not applied:
                return False
        return True

    async def record_attempt_outcome(
        self,
        *,
        enrollment_id: str,
        outcome: AutopayAttemptOutcome,
        occurred_at: datetime,
        failure_code: str | None,
    ) -> None:
        """Record a projection of the latest charge attempt outcome.

        Deliberately independent of `autopay_enrollment_status`: a declined or
        errored charge does not change enrollment state. Dunning/retry policy
        (Slice H) reacts to this projection separately.
        """
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$set": {
                    "last_attempt_outcome": outcome,
                    "last_attempt_at": occurred_at,
                    "last_failure_code": failure_code,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
