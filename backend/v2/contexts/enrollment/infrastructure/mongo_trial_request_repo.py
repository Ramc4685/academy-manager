"""Mongo repository for parent-submitted trial class requests (R3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.domain.self_service import GuestBookingRefusal, TrialRequest
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import ensure_utc


class MongoTrialRequestRepository(TenantScopedRepository):
    collection_name = "trial_requests"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> TrialRequest:
        return TrialRequest(
            request_id=str(doc["request_id"]),
            academy_id=str(doc["academy_id"]),
            parent_user_id=_optional_str(doc.get("parent_user_id")),
            student_ref=doc["student_ref"],
            student_id=_optional_str(doc.get("student_id")),
            prospective_child_name=_optional_str(doc.get("prospective_child_name")),
            prospective_child_dob=_optional_str(doc.get("prospective_child_dob")),
            requested_session_id=str(doc["requested_session_id"]),
            preferred_start=str(doc["preferred_start"]),
            preferred_end=str(doc["preferred_end"]),
            status=doc.get("status", "pending"),
            assigned_occurrence_id=_optional_str(doc.get("assigned_occurrence_id")),
            linked_application_id=_optional_str(doc.get("linked_application_id")),
            denial_reason=_optional_str(doc.get("denial_reason")),
            decided_by=_optional_str(doc.get("decided_by")),
            decided_at=_optional_utc(doc.get("decided_at")),
            created_at=_utc(doc["created_at"]),
            outcome=doc.get("outcome"),
            outcome_by=_optional_str(doc.get("outcome_by")),
            outcome_at=_optional_utc(doc.get("outcome_at")),
            contact_id=_optional_str(doc.get("contact_id")),
            guest_slot=_optional_int(doc.get("guest_slot")),
            guest_name=_optional_str(doc.get("guest_name")),
            guest_age=_optional_str(doc.get("guest_age")),
            guest_mailbox=_optional_str(doc.get("guest_mailbox")),
            guest_day_claim=_optional_str(doc.get("guest_day_claim")),
            guest_starts_at=_optional_utc(doc.get("guest_starts_at")),
        )

    @staticmethod
    def _to_doc(request: TrialRequest) -> dict[str, object]:
        return {
            "request_id": request.request_id,
            "academy_id": current_academy_id(),
            "parent_user_id": request.parent_user_id,
            "student_ref": request.student_ref,
            "student_id": request.student_id,
            "prospective_child_name": request.prospective_child_name,
            "prospective_child_dob": request.prospective_child_dob,
            "requested_session_id": request.requested_session_id,
            "preferred_start": request.preferred_start,
            "preferred_end": request.preferred_end,
            "status": request.status,
            "assigned_occurrence_id": request.assigned_occurrence_id,
            "linked_application_id": request.linked_application_id,
            "denial_reason": request.denial_reason,
            "decided_by": request.decided_by,
            "decided_at": request.decided_at,
            "created_at": request.created_at,
            "outcome": request.outcome,
            "outcome_by": request.outcome_by,
            "outcome_at": request.outcome_at,
            "contact_id": request.contact_id,
            "guest_slot": request.guest_slot,
            "guest_name": request.guest_name,
            "guest_age": request.guest_age,
            "guest_mailbox": request.guest_mailbox,
            "guest_day_claim": request.guest_day_claim,
            "guest_starts_at": request.guest_starts_at,
        }

    async def add(self, request: TrialRequest) -> None:
        await self._insert_one(self._to_doc(request))

    async def get(self, request_id: str) -> TrialRequest | None:
        doc = await self._find_one({"request_id": request_id})
        return self._to_domain(doc) if doc else None

    async def list_for_parent(self, parent_user_id: str) -> list[TrialRequest]:
        cursor = self._find_many({"parent_user_id": parent_user_id}, sort=[("created_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_by_status(self, status: str | None) -> list[TrialRequest]:
        query: dict[str, object] = {} if status is None else {"status": status}
        cursor = self._find_many(query, sort=[("created_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def find_pending_for_parent_and_session(
        self, parent_user_id: str, session_id: str
    ) -> TrialRequest | None:
        doc = await self._find_one(
            {
                "parent_user_id": parent_user_id,
                "requested_session_id": session_id,
                "status": "pending",
            }
        )
        return self._to_domain(doc) if doc else None

    async def find_latest_convertible_for_parent(self, parent_user_id: str) -> TrialRequest | None:
        cursor = self._find_many(
            {
                "parent_user_id": parent_user_id,
                "status": {"$in": ["approved", "completed"]},
                "linked_application_id": None,
            },
            sort=[("created_at", -1)],
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None

    async def update(self, request: TrialRequest) -> None:
        await self._update_one(
            {"request_id": request.request_id},
            {"$set": self._to_doc(request)},
        )

    async def reopen_for_assigned_occurrence(self, occurrence_id: str) -> list[TrialRequest]:
        """Put approved trials assigned to a now-cancelled date back to
        ``pending`` and return them as they were (issue #671).

        The mirror of ``MongoMakeupRequestRepository.reopen_for_target_occurrence``.
        Without it a trial stays ``approved`` against an occurrence that will
        never run, with its roster seat already deleted: no admin queue shows
        it, nothing re-offers it, and the trial is silently lost. The requests
        are returned so the caller can tell the family (a trial family has no
        enrollment on the session and is invisible to the roster notifier). A
        website guest's seat number is cleared too, freeing the seat (L9).
        """
        cursor = self._find_many(
            {"status": "approved", "assigned_occurrence_id": occurrence_id},
            sort=[("created_at", 1)],
        )
        docs = [doc async for doc in cursor]
        if not docs:
            return []
        await self.collection.update_many(
            self._scoped({"request_id": {"$in": [str(doc["request_id"]) for doc in docs]}}),
            {
                "$set": {
                    "status": "pending",
                    "assigned_occurrence_id": None,
                    "decided_by": None,
                    "decided_at": None,
                },
                "$unset": {"guest_slot": ""},
            },
        )
        return [self._to_domain(doc) for doc in docs]

    # --- website guest bookings (L9 A6-1, migration 0236) -------------------

    async def add_guest(
        self, request: TrialRequest, *, max_slot: int, day_ceiling: int
    ) -> TrialRequest | GuestBookingRefusal:
        """Insert a guest booking with the lowest free seat number in
        ``1..max_slot`` on its date and the lowest free daily number in
        ``1..day_ceiling`` for its UTC day, or say which limit refused it.

        Three unique indexes (migration 0236) are the arbiters, so concurrent
        bookings cannot overrun any of them: a taken seat or day number moves
        that counter on, and a second booking of the same class by the same
        ``guest_mailbox`` is refused outright."""
        day = request.created_at.astimezone(UTC).date().isoformat()
        slot, number = 1, 1
        while slot <= max_slot and number <= day_ceiling:
            seated = request.model_copy(
                update={"guest_slot": slot, "guest_day_claim": f"{day}#{number}"}
            )
            try:
                await self._insert_one(self._to_doc(seated))
            except DuplicateKeyError as exc:
                field = _collided_guest_field(exc)
                if field == "guest_slot":
                    slot += 1
                elif field == "guest_day_claim":
                    number += 1
                elif field == "guest_mailbox":
                    return "mailbox_limit"
                else:
                    raise
                continue
            return seated
        return "full" if slot > max_slot else "academy_ceiling"

    async def approve_guest(
        self, request_id: str, updates: dict[str, object], *, max_slot: int
    ) -> TrialRequest | None:
        """``transition_from_pending`` for a guest: the approval also takes the
        lowest free seat number on the new date. None when the request is no
        longer pending or every seat number up to ``max_slot`` is taken."""
        for slot in range(1, max_slot + 1):
            try:
                return await self.transition_from_pending(
                    request_id, {**updates, "guest_slot": slot}
                )
            except DuplicateKeyError as exc:
                if _collided_guest_field(exc) != "guest_slot":
                    raise
        return None

    async def guest_counts_for_occurrences(self, occurrence_ids: list[str]) -> dict[str, int]:
        """Seated guests per class date, one aggregation on the slot index."""
        ids = [oid for oid in dict.fromkeys(occurrence_ids) if oid]
        if not ids:
            return {}
        pipeline: list[dict[str, Any]] = [
            {
                "$match": self._scoped(
                    {"assigned_occurrence_id": {"$in": ids}, "guest_slot": {"$gte": 1}}
                )
            },
            {"$group": {"_id": "$assigned_occurrence_id", "count": {"$sum": 1}}},
        ]
        return {
            str(doc["_id"]): int(doc["count"]) async for doc in self.collection.aggregate(pipeline)
        }

    async def guests_for_occurrence(self, occurrence_id: str) -> list[TrialRequest]:
        """The seated guests on one class date, in seat order."""
        cursor = self._find_many(
            {"assigned_occurrence_id": occurrence_id, "guest_slot": {"$gte": 1}},
            sort=[("guest_slot", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def latest_guest_booking(self, contact_id: str) -> TrialRequest | None:
        """This contact's newest guest booking, on the contact index."""
        cursor = self._find_many(
            {"contact_id": {"$eq": contact_id, "$gt": ""}}, sort=[("created_at", -1)], limit=1
        )
        return next(iter([self._to_domain(doc) async for doc in cursor]), None)

    async def count_active_guests(self, mailbox: str, *, now: datetime) -> int:
        """Approved guest bookings of this canonical inbox whose date has not
        started yet: the per-academy mailbox limit."""
        return await self._count(
            {
                "guest_mailbox": {"$eq": mailbox, "$gt": ""},
                "status": "approved",
                "guest_starts_at": {"$gt": now},
            }
        )

    async def cancel_guest_booking(self, request_id: str) -> TrialRequest | None:
        """Staff cancel one approved guest booking (L9): back to ``pending``
        with its seat, inbox and day claims released, as a cancelled date does
        for every trial on it. Compare-and-swap on the approved guest row;
        returns the row as it was, or None when it is not one any more."""
        doc = await self._find_one_and_update(
            {"request_id": request_id, "status": "approved", "contact_id": {"$gt": ""}},
            {
                "$set": {
                    "status": "pending",
                    "assigned_occurrence_id": None,
                    "decided_by": None,
                    "decided_at": None,
                },
                "$unset": {
                    "guest_slot": "",
                    "guest_mailbox": "",
                    "guest_day_claim": "",
                    "guest_starts_at": "",
                },
            },
            return_document_after=False,
        )
        return self._to_domain(doc) if doc else None

    async def transition_from_pending(
        self, request_id: str, updates: dict[str, object]
    ) -> TrialRequest | None:
        """Atomically move a request out of ``pending`` iff it is still
        ``pending``, applying ``updates`` in the same ``$set``. Mirrors
        ``MongoMakeupRequestRepository.transition_from_pending`` — the CAS
        (find_one_and_update filtered on {request_id, status: "pending"})
        means two concurrent approve/deny calls for the SAME request can't
        both succeed. Returns ``None`` if not found or no longer pending.
        """
        update: dict[str, Any] = {"$set": updates}
        if updates.get("status") == "denied":
            # A declined guest frees its inbox and day claims, so staff can
            # release an inbox that was squatted or whose date was cancelled.
            update["$unset"] = {"guest_mailbox": "", "guest_day_claim": ""}
        doc = await self._find_one_and_update(
            {"request_id": request_id, "status": "pending"}, update
        )
        return self._to_domain(doc) if doc else None

    async def record_outcome(
        self, request_id: str, updates: dict[str, object]
    ) -> TrialRequest | None:
        """Atomically record Came / Didn't come iff the request can still take
        an outcome (``approved``, or ``completed`` for a correction).

        Same compare-and-swap shape as ``transition_from_pending``: the status
        filter rides in the ``find_one_and_update``, so a trial that was
        converted (or reopened by a cancelled date) between the caller's read
        and this write is left alone and ``None`` comes back.
        """
        doc = await self._find_one_and_update(
            {"request_id": request_id, "status": {"$in": ["approved", "completed"]}},
            {"$set": updates},
        )
        return self._to_domain(doc) if doc else None

    async def outcomes_for(self, request_ids: list[str]) -> dict[str, str | None]:
        """``{request_id: outcome}`` for these requests in this academy (one
        read). Ids of other academies, or unknown ids, are simply absent."""
        ids = [rid for rid in dict.fromkeys(request_ids) if rid]
        if not ids:
            return {}
        cursor = self._find_many({"request_id": {"$in": ids}})
        return {str(doc["request_id"]): doc.get("outcome") async for doc in cursor}


def _optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object | None) -> int | None:
    return None if value is None else int(cast(int, value))


_GUEST_CLAIM_FIELDS = ("guest_slot", "guest_day_claim", "guest_mailbox")


def _collided_guest_field(exc: DuplicateKeyError) -> str | None:
    """Which guest claim index a duplicate hit, or None for any other index."""
    key_pattern = (exc.details or {}).get("keyPattern") or {}
    return next((f for f in _GUEST_CLAIM_FIELDS if f in key_pattern), None)


def _utc(value: object) -> datetime:
    """A BSON datetime read back naive, as the aware UTC instant it always was (#706)."""
    return ensure_utc(cast(datetime, value))


def _optional_utc(value: object | None) -> datetime | None:
    return None if value is None else _utc(value)
