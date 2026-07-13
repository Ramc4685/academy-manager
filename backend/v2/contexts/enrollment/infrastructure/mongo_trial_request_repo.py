"""Mongo repository for parent-submitted trial class requests (R3)."""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoTrialRequestRepository(TenantScopedRepository):
    collection_name = "trial_requests"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> TrialRequest:
        return TrialRequest(
            request_id=str(doc["request_id"]),
            academy_id=str(doc["academy_id"]),
            parent_user_id=str(doc["parent_user_id"]),
            student_ref=doc["student_ref"],  # type: ignore[arg-type]
            student_id=_optional_str(doc.get("student_id")),
            prospective_child_name=_optional_str(doc.get("prospective_child_name")),
            prospective_child_dob=_optional_str(doc.get("prospective_child_dob")),
            requested_session_id=str(doc["requested_session_id"]),
            preferred_start=str(doc["preferred_start"]),
            preferred_end=str(doc["preferred_end"]),
            status=doc.get("status", "pending"),  # type: ignore[arg-type]
            assigned_occurrence_id=_optional_str(doc.get("assigned_occurrence_id")),
            linked_application_id=_optional_str(doc.get("linked_application_id")),
            denial_reason=_optional_str(doc.get("denial_reason")),
            decided_by=_optional_str(doc.get("decided_by")),
            decided_at=doc.get("decided_at"),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
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


def _optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)
