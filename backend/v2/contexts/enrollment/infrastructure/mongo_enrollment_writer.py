"""EnrollmentWriter."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentWriter(TenantScopedRepository):
    collection_name = "enrollments"

    async def create(self, enrollment: Enrollment) -> None:
        doc = enrollment.model_dump(mode="python")
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def create_if_absent(self, enrollment: Enrollment) -> bool:
        """Atomically create a deterministic enrollment once.

        Registration approval can be submitted concurrently. The caller uses
        the boolean to release any duplicate seat reservation.
        """
        doc = enrollment.model_dump(mode="python")
        try:
            result = await self._update_one(
                {"enrollment_id": enrollment.enrollment_id},
                {"$setOnInsert": {k: v for k, v in doc.items() if k != "academy_id"}},
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return result.upserted_id is not None

    #: Statuses that END an enrollment. Reaching one retires any scheduled
    #: end-of-period cancel marker: an admin who cancels or withdraws on the
    #: 20th must not leave the roster showing "Ends Sep 30" for a student who
    #: is already off it (issue #675 follow-up). Issue #699: both spellings of
    #: each terminal status, so this still catches legacy rows.
    _TERMINAL_STATUSES = frozenset({"cancelled", "deleted", "withdrawn", "dropped"})

    async def update_status(self, enrollment_id: str, status: str) -> None:
        fields: dict[str, object] = {"status": status}
        if status in self._TERMINAL_STATUSES:
            fields["pending_cancellation_at"] = None
        await self._update_one({"enrollment_id": enrollment_id}, {"$set": fields})

    async def set_lifecycle_dates(
        self,
        enrollment_id: str,
        *,
        cancelled_at: datetime | None = None,
        withdrawal_date: datetime | None = None,
        cancelled_by: str | None = None,
        cancellation_reason: str | None = None,
    ) -> None:
        """Persist the effective date of a cancel/withdraw (issue #651) and,
        issue #674, who ended it and why, so the student's past-enrollment row
        can show the actor and reason without a join on the event log. The
        actor defaults to "admin" when a cancel date is stamped (the parent
        self-cancel path has its own writer and never comes through here).
        """
        fields: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if cancelled_at is not None:
            fields["cancelled_at"] = cancelled_at
            fields["cancelled_by"] = cancelled_by or "admin"
        elif cancelled_by is not None:
            fields["cancelled_by"] = cancelled_by
        if withdrawal_date is not None:
            fields["withdrawal_date"] = withdrawal_date
        if cancellation_reason is not None and cancellation_reason.strip():
            fields["cancellation_reason"] = cancellation_reason.strip()
        await self._update_one({"enrollment_id": enrollment_id}, {"$set": fields})

    #: Statuses a withdrawal may start from (issue #670; widened by #697 to
    #: include ``held`` — Drop must work on a held enrollment). Legacy rows
    #: with no ``status`` field read as ``active`` everywhere else, so they
    #: are open too.
    _WITHDRAWABLE_FILTER: ClassVar[dict[str, object]] = {
        "$or": [
            {"status": {"$in": ["active", "paused", "held"]}},
            {"status": {"$exists": False}},
        ]
    }

    async def mark_held_if_active(
        self,
        enrollment_id: str,
        *,
        started_at: datetime,
        return_on: date,
        expires_at: datetime,
        reason: str | None,
    ) -> Enrollment | None:
        """CAS ``active`` -> ``held`` (issue #697). Never touches
        reserved_seats — the row keeps its seat."""
        doc = await self._find_one_and_update(
            {"enrollment_id": enrollment_id, "status": "active"},
            {
                "$set": {
                    "status": "held",
                    "hold_started_at": started_at,
                    "hold_return_on": return_on.isoformat(),
                    "hold_expires_at": expires_at,
                    "hold_reason": reason,
                    "hold_reclaim_claimed_at": None,
                    "hold_reclaim_for": None,
                    "hold_reclaim_failed_at": None,
                    "updated_at": datetime.now(UTC),
                },
                "$inc": {"hold_seq": 1},
            },
            return_document_after=False,
        )
        return self._to_domain(doc) if doc else None

    async def mark_active_if_held(self, enrollment_id: str) -> Enrollment | None:
        """CAS ``held`` -> ``active`` (Return, issue #697).

        MUST NOT reserve a seat — it was never released. This method
        performs no seat arithmetic and callers must not add any."""
        doc = await self._find_one_and_update(
            {"enrollment_id": enrollment_id, "status": "held"},
            {
                "$set": {
                    "status": "active",
                    "updated_at": datetime.now(UTC),
                },
                "$unset": {
                    "hold_started_at": "",
                    "hold_return_on": "",
                    "hold_expires_at": "",
                    "hold_reason": "",
                },
            },
            return_document_after=False,
        )
        return self._to_domain(doc) if doc else None

    async def delete_if_status(
        self, enrollment_id: str, *, allowed: frozenset[str]
    ) -> Enrollment | None:
        """CAS: hard-delete the row iff its status is in ``allowed``. Returns
        the pre-image so the caller knows whether to release a seat."""
        doc = await self._find_one_and_update(
            {"enrollment_id": enrollment_id, "status": {"$in": sorted(allowed)}},
            {"$set": {"status": "__deleting__"}},
            return_document_after=False,
        )
        if doc is None:
            return None
        await self._delete_one({"enrollment_id": enrollment_id})
        return self._to_domain(doc)

    async def mark_withdrawn_if_open(
        self, enrollment_id: str, *, withdrawal_date: datetime
    ) -> Enrollment | None:
        """CAS ``active``/``paused``/``held`` -> ``dropped`` (issue #670,
        widened #697, renamed #699 — was "withdrawn"; see
        domain/models.py canonical_status()). Returns the pre-image so the
        caller knows whether the row held a seat; ``None`` when the row was
        not open, which is how a concurrent double-submit loses without a
        second seat release."""
        doc = await self._find_one_and_update(
            {"enrollment_id": enrollment_id, **self._WITHDRAWABLE_FILTER},
            {
                "$set": {
                    "status": "dropped",
                    "withdrawal_date": withdrawal_date,
                    "updated_at": datetime.now(UTC),
                }
            },
            return_document_after=False,
        )
        return self._to_domain(doc) if doc else None

    async def mark_cancelled_by_parent(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        cancellation_policy_snapshot: dict[str, object],
        cancelled_at: datetime,
    ) -> Enrollment | None:
        """Atomically transition active -> cancelled for a parent self-cancel
        (R4). Same CAS shape as ``mark_withdrawn_if_open``: it uses the helper
        (``_find_one_and_update`` filtered on ``status: "active"``) so a
        double-submitted cancel can't both succeed — the loser gets ``None``
        back and the use case raises ``EnrollmentNotCancellable``. Always
        stamps the full audit trail in the same write — never a silent
        state change.
        """
        doc = await self._find_one_and_update(
            {"enrollment_id": enrollment_id, "status": "active"},
            {
                "$set": {
                    # Issue #699 deliberately does NOT rename this write:
                    # the parent self-cancel surface (R4) is out of scope
                    # for the departures vocabulary migration (same boundary
                    # as the design contract's self-service protections in
                    # #697 §5.2) and its response DTO
                    # (SelfCancelEnrollmentResult.status) is a documented
                    # parent-facing API contract this slice does not touch.
                    # Read paths already accept both spellings via
                    # canonical_status()/SEATLESS, so this row is read
                    # correctly either way.
                    "status": "cancelled",
                    "cancelled_by": "parent",
                    "cancellation_reason": cancellation_reason,
                    "cancellation_policy_snapshot": cancellation_policy_snapshot,
                    "cancelled_at": cancelled_at,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        return self._to_domain(doc) if doc else None

    async def mark_pending_cancellation_by_parent(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        cancellation_policy_snapshot: dict[str, object],
        pending_cancellation_at: datetime,
        requested_at: datetime,
    ) -> Enrollment | None:
        """Issue #675 (``end_of_period`` timing): record that a parent asked
        to cancel at month end WITHOUT flipping ``status``. CAS on
        ``status: "active"`` AND no pending cancellation, so a double-submit
        (or a second request after the first was accepted) loses and the use
        case raises ``EnrollmentNotCancellable`` instead of enqueueing twice.
        The reason and policy snapshot are stamped now (they are the
        decision's audit trail); ``cancelled_by`` / ``cancelled_at`` are
        stamped by ``complete_pending_cancellation`` when the flip happens.
        """
        doc = await self._find_one_and_update(
            {
                "enrollment_id": enrollment_id,
                "status": "active",
                "pending_cancellation_at": None,
            },
            {
                "$set": {
                    "cancellation_reason": cancellation_reason,
                    "cancellation_policy_snapshot": cancellation_policy_snapshot,
                    "pending_cancellation_at": pending_cancellation_at,
                    "pending_cancellation_requested_at": requested_at,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        return self._to_domain(doc) if doc else None

    async def complete_pending_cancellation(
        self, enrollment_id: str, *, cancelled_at: datetime
    ) -> Enrollment | None:
        """Issue #675: the scheduled ``cancel_at_period_end`` action fires.
        CAS on "still pending and not yet ended" (active — or paused, since an
        admin pause keeps the pending cancellation — or held, since a hold
        also keeps the pending cancellation and, unlike pause, never released
        the seat) so an admin cancel / withdraw that landed first wins and
        this returns ``None``. A ``held`` row must be included here: a parent
        self-cancels at period end, an admin holds the child before month
        end, and the CAS must still recognize the row as "not yet ended" — a
        real Mongo incident had this CAS filter (and the seated-status set
        below in ``process_scheduled_cancellation_actions``) omit ``held``,
        which made the scheduled action match nothing, log the dishonest
        reason ``enrollment_already_ended:held`` (the row was never ended),
        and retire the action permanently while the family kept being
        invoiced forever. Returns the PRE-image so the processor knows
        whether the row still held a seat (an active or held row does, a
        paused row released it when it paused).
        """
        doc = await self._find_one_and_update(
            {
                "enrollment_id": enrollment_id,
                "status": {"$in": ["active", "paused", "held"]},
                "pending_cancellation_at": {"$ne": None},
            },
            {
                "$set": {
                    # Issue #699: deliberately NOT renamed — this is the
                    # end-of-period arm of the same parent self-cancel
                    # surface as mark_cancelled_by_parent above; see that
                    # method's comment for why it stays out of scope here.
                    "status": "cancelled",
                    "cancelled_by": "parent",
                    "cancelled_at": cancelled_at,
                    "pending_cancellation_at": None,
                    "updated_at": datetime.now(UTC),
                }
            },
            return_document_after=False,
        )
        return self._to_domain(doc) if doc else None

    async def mark_fee_billing_error(self, enrollment_id: str, *, error: str) -> None:
        """Targeted stamp of a failed self-cancel fee billing attempt onto
        the audit snapshot (admin-visibility rule: "Admin must see
        unrecovered failures"). Deliberately separate from
        ``mark_cancelled_by_parent`` — the CAS write already committed the
        cancellation; this is a best-effort follow-up write, not part of
        that atomic transition, and is intentionally unconditional (no CAS
        filter) since the enrollment is already cancelled by this point."""
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$set": {
                    "cancellation_policy_snapshot.fee_billing_error": error,
                    "updated_at": datetime.now(UTC),
                }
            },
        )

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        existing = await self._find_one({"enrollment_id": enrollment_id})
        previous_session_id = existing.get("session_id") if existing else None
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$set": {"session_id": session_id},
                "$push": {
                    "move_history": {
                        "from_session_id": previous_session_id,
                        "to_session_id": session_id,
                        "moved_at": datetime.now(UTC),
                    }
                },
            },
        )

    async def update_amount_cents(self, enrollment_id: str, amount_cents: int | None) -> None:
        update: dict[str, object]
        if amount_cents is None:
            update = {
                "$unset": {
                    "amount_cents": "",
                    "gross_amount_cents": "",
                    "final_amount_cents": "",
                    "monthly_price_cents": "",
                    "price_cents": "",
                },
                "$set": {"updated_at": datetime.now(UTC)},
            }
        else:
            update = {
                "$set": {
                    "amount_cents": amount_cents,
                    "gross_amount_cents": amount_cents,
                    "final_amount_cents": amount_cents,
                    "updated_at": datetime.now(UTC),
                }
            }
        await self._update_one({"enrollment_id": enrollment_id}, update)

    async def add_skip_period(self, enrollment_id: str, period: str) -> None:
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$addToSet": {"skip_periods": period},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )

    async def set_enrolled_at_if_missing(self, enrollment_id: str, enrolled_at: datetime) -> None:
        await self._update_one(
            {
                "enrollment_id": enrollment_id,
                "$or": [{"enrolled_at": {"$exists": False}}, {"enrolled_at": None}],
            },
            {"$set": {"enrolled_at": enrolled_at, "updated_at": datetime.now(UTC)}},
        )

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Enrollment:
        # Older rows stored the hold return date as an ISO string; newer ones
        # store a real date. Narrow it once, here, rather than at every field.
        hold_return_on = doc.get("hold_return_on")
        if isinstance(hold_return_on, str):
            hold_return_on = date.fromisoformat(hold_return_on)
        return Enrollment(
            enrollment_id=str(doc["enrollment_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            status=doc.get("status", "active"),
            enrolled_at=doc.get("enrolled_at"),
            created_at=doc.get("created_at"),
            registration_application_id=doc.get("registration_application_id"),
            registration_student_lock=doc.get("registration_student_lock"),
            cancelled_by=doc.get("cancelled_by"),
            cancellation_reason=doc.get("cancellation_reason"),
            cancellation_policy_snapshot=doc.get("cancellation_policy_snapshot"),
            cancelled_at=doc.get("cancelled_at"),
            pending_cancellation_at=doc.get("pending_cancellation_at"),
            pending_cancellation_requested_at=doc.get("pending_cancellation_requested_at"),
            hold_started_at=doc.get("hold_started_at"),
            hold_return_on=hold_return_on,
            hold_expires_at=doc.get("hold_expires_at"),
            hold_reason=doc.get("hold_reason"),
            hold_seq=doc.get("hold_seq", 0),
            hold_reclaim_claimed_at=doc.get("hold_reclaim_claimed_at"),
            hold_reclaim_for=doc.get("hold_reclaim_for"),
            hold_reclaim_failed_at=doc.get("hold_reclaim_failed_at"),
        )

    async def get(self, enrollment_id: str) -> Enrollment | None:
        doc = await self._find_one({"enrollment_id": enrollment_id})
        return self._to_domain(doc) if doc else None

    async def list_cancelled_by_parent(self) -> list[Enrollment]:
        """Enrollments a parent self-cancelled (R4 admin audit list), newest
        ``cancelled_at`` first."""
        cursor = self._find_many({"cancelled_by": "parent"}, sort=[("cancelled_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def count_active_for_session(self, session_id: str) -> int:
        # Issue #697: counts SEAT_HOLDING (active + held), not just active —
        # else a class full of holds reports "counter drift" (contract §2.5).
        from backend.v2.contexts.enrollment.domain.models import SEAT_HOLDING

        return await self.collection.count_documents(
            self._scoped({"session_id": session_id, "status": {"$in": sorted(SEAT_HOLDING)}})
        )

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        base_filter = {"session_id": session_id, "student_id": student_id}
        doc = await self._find_one({**base_filter, "status": "active"})
        if doc is None:
            doc = await self._find_one({**base_filter, "status": {"$exists": False}})
        if doc is None:
            doc = await self._find_one({**base_filter, "status": "paused"})
        if doc is None:
            doc = await self._find_one(base_filter)
        return self._to_domain(doc) if doc else None
