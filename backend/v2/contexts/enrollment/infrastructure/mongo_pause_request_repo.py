"""Mongo pause request repository."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    PauseRequest,
)
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoPauseRequestRepository(TenantScopedRepository):
    collection_name = "pause_requests"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> PauseRequest:
        return PauseRequest(
            pause_request_id=str(doc["pause_request_id"]),
            enrollment_id=str(doc["enrollment_id"]),
            parent_id=str(doc["parent_id"]),
            period=str(doc["period"]),
            reason=str(doc.get("reason") or ""),
            status=doc.get("status", "pending"),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
            decided_at=doc.get("decided_at"),  # type: ignore[arg-type]
            decided_by=doc.get("decided_by"),  # type: ignore[arg-type]
        )

    async def add(self, request: PauseRequest) -> None:
        await self._insert_one(request.model_dump(mode="python"))

    async def get(self, pause_request_id: str) -> PauseRequest | None:
        doc = await self._find_one({"pause_request_id": pause_request_id})
        return self._to_domain(doc) if doc else None

    async def list_for_parent(self, parent_id: str) -> list[PauseRequest]:
        cursor = self._find_many(
            {"parent_id": parent_id},
            sort=[("created_at", -1)],
            limit=100,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_pending(self) -> list[PauseRequest]:
        cursor = self._find_many(
            {"status": "pending"},
            sort=[("created_at", 1)],
            limit=200,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def approve(self, pause_request_id: str, *, admin_id: str) -> PauseRequest:
        request = await self.get(pause_request_id)
        if request is None:
            raise EnrollmentNotFound("pause request missing", pause_request_id=pause_request_id)
        now = datetime.now(timezone.utc)
        await self._update_one(
            {"pause_request_id": pause_request_id},
            {"$set": {"status": "approved", "decided_at": now, "decided_by": admin_id}},
        )
        await self._db["enrollments"].update_one(
            {"academy_id": current_academy_id(), "enrollment_id": request.enrollment_id},
            {
                "$addToSet": {"skip_periods": request.period},
                "$set": {"updated_at": now},
            },
        )
        return request.model_copy(
            update={"status": "approved", "decided_at": now, "decided_by": admin_id}
        )

    async def decline(self, pause_request_id: str, *, admin_id: str) -> PauseRequest:
        request = await self.get(pause_request_id)
        if request is None:
            raise EnrollmentNotFound("pause request missing", pause_request_id=pause_request_id)
        now = datetime.now(timezone.utc)
        await self._update_one(
            {"pause_request_id": pause_request_id},
            {"$set": {"status": "declined", "decided_at": now, "decided_by": admin_id}},
        )
        return request.model_copy(
            update={"status": "declined", "decided_at": now, "decided_by": admin_id}
        )

    async def enrollment_belongs_to_parent(self, enrollment_id: str, parent_id: str) -> bool:
        academy_id = current_academy_id()
        enrollment = await self._db["enrollments"].find_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id}
        )
        if not enrollment:
            return False
        student = await self._db["students"].find_one(
            {"academy_id": academy_id, "student_id": enrollment.get("student_id")}
        )
        return bool(
            student and str(student.get("parent_id") or student.get("parent_user_id")) == parent_id
        )
