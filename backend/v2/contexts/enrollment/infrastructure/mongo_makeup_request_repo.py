"""Mongo repository for parent-submitted makeup requests."""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.self_service import MakeupRequest
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoMakeupRequestRepository(TenantScopedRepository):
    collection_name = "makeup_requests"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> MakeupRequest:
        return MakeupRequest(
            request_id=str(doc["request_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            parent_id=str(doc["parent_id"]),
            missed_occurrence_id=str(doc["missed_occurrence_id"]),
            requested_target_occurrence_id=_optional_str(doc.get("requested_target_occurrence_id")),
            status=doc.get("status", "pending"),  # type: ignore[arg-type]
            expires_at=doc["expires_at"],  # type: ignore[arg-type]
            denial_reason=_optional_str(doc.get("denial_reason")),
            decided_by=_optional_str(doc.get("decided_by")),
            decided_at=doc.get("decided_at"),  # type: ignore[arg-type]
            approved_target_occurrence_id=_optional_str(doc.get("approved_target_occurrence_id")),
            created_at=doc["created_at"],  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_doc(request: MakeupRequest) -> dict[str, object]:
        return {
            "request_id": request.request_id,
            "academy_id": current_academy_id(),
            "student_id": request.student_id,
            "parent_id": request.parent_id,
            "missed_occurrence_id": request.missed_occurrence_id,
            "requested_target_occurrence_id": request.requested_target_occurrence_id,
            "status": request.status,
            "expires_at": request.expires_at,
            "denial_reason": request.denial_reason,
            "decided_by": request.decided_by,
            "decided_at": request.decided_at,
            "approved_target_occurrence_id": request.approved_target_occurrence_id,
            "created_at": request.created_at,
        }

    async def add(self, request: MakeupRequest) -> None:
        await self._insert_one(self._to_doc(request))

    async def get(self, request_id: str) -> MakeupRequest | None:
        doc = await self._find_one({"request_id": request_id})
        return self._to_domain(doc) if doc else None

    async def list_for_parent(self, parent_id: str) -> list[MakeupRequest]:
        cursor = self._find_many({"parent_id": parent_id}, sort=[("created_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_by_status(self, status: str | None) -> list[MakeupRequest]:
        query: dict[str, object] = {} if status is None else {"status": status}
        cursor = self._find_many(query, sort=[("created_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def find_active_for_missed_occurrence(
        self, missed_occurrence_id: str, student_id: str
    ) -> MakeupRequest | None:
        doc = await self._find_one(
            {
                "missed_occurrence_id": missed_occurrence_id,
                "student_id": student_id,
                "status": {"$ne": "denied"},
            }
        )
        return self._to_domain(doc) if doc else None

    async def update(self, request: MakeupRequest) -> None:
        await self._update_one(
            {"request_id": request.request_id},
            {"$set": self._to_doc(request)},
        )


def _optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)
