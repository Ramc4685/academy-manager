"""Mongo repository for parent-submitted trial class requests (R3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
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

    async def add_guest(self, request: TrialRequest, *, max_slot: int) -> TrialRequest | None:
        """Insert a guest booking on the lowest free seat number in
        ``1..max_slot`` of its assigned date, or return None when every seat
        is taken. The unique ``trial_requests_guest_slot_unique`` index is the
        arbiter: a concurrent booking that took the same number makes this
        insert fail and move on, so the last seat goes to exactly one row."""
        for slot in range(1, max_slot + 1):
            seated = request.model_copy(update={"guest_slot": slot})
            try:
                await self._insert_one(self._to_doc(seated))
            except DuplicateKeyError as exc:
                if not _is_guest_slot_collision(exc):
                    raise
                continue
            return seated
        return None

    async def approve_guest(
        self, request_id: str, updates: dict[str, object], *, max_slot: int
    ) -> TrialRequest | None:
        """``transition_from_pending`` for a guest: the approval also takes the
        lowest free seat number on the new date. None when the request is no
        longer pending or every seat number up to ``max_slot`` is taken."""
        occurrence_id = updates.get("assigned_occurrence_id")
        for slot in range(1, max_slot + 1):
            try:
                return await self.transition_from_pending(
                    request_id, {**updates, "guest_slot": slot}
                )
            except DuplicateKeyError as exc:
                if not _is_guest_slot_collision(exc) or occurrence_id is None:
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

    async def count_active_guests(
        self, contact_ids: list[str], *, since: datetime, session_id: str | None = None
    ) -> int:
        """Approved guest bookings of these contacts made at or after ``since``
        (optionally for one class): the per-mailbox booking limits."""
        ids = [cid for cid in dict.fromkeys(contact_ids) if cid]
        if not ids:
            return 0
        query: dict[str, object] = {
            "contact_id": {"$in": ids, "$gt": ""},
            "status": "approved",
            "created_at": {"$gte": since},
        }
        if session_id is not None:
            query["requested_session_id"] = session_id
        return await self._count(query)

    async def count_guests_since(self, since: datetime) -> int:
        """Every guest booking this academy took at or after ``since``."""
        return await self._count({"contact_id": {"$gt": ""}, "created_at": {"$gte": since}})

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
        doc = await self._find_one_and_update(
            {"request_id": request_id, "status": "pending"},
            {"$set": updates},
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


def _is_guest_slot_collision(exc: DuplicateKeyError) -> bool:
    details = exc.details or {}
    if details.get("keyPattern"):
        return "guest_slot" in details["keyPattern"]
    return "guest_slot" in str(exc)


def _utc(value: object) -> datetime:
    """A BSON datetime read back naive, as the aware UTC instant it always was (#706)."""
    return ensure_utc(cast(datetime, value))


def _optional_utc(value: object | None) -> datetime | None:
    return None if value is None else _utc(value)
