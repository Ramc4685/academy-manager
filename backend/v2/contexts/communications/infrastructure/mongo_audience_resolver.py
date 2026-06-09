"""Mongo-backed audience resolver.

Resolves audience descriptors to concrete recipient lists by querying
the users, enrollments, and students collections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    CoachAudience,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
)
from backend.v2.shared.tenancy.context import current_academy_id


@dataclass
class MongoAudienceResolver(AudienceResolver):
    db: AsyncIOMotorDatabase

    def _role_filter(self, role: str) -> dict[str, Any]:
        return {
            "academy_id": current_academy_id(),
            "$or": [{"role": role}, {"roles": role}],
        }

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        cursor = self.db["users"].find(
            self._role_filter(audience.role),
            {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        return [self._user_to_recipient(doc) async for doc in cursor]

    async def resolve_session_audience(self, audience: SessionAudience) -> list[ResolvedRecipient]:
        academy_id = current_academy_id()
        enrollment_cursor = self.db["enrollments"].find(
            {"academy_id": academy_id, "session_id": audience.session_id, "status": "active"},
            {"student_id": 1},
        )
        student_ids = [str(doc["student_id"]) async for doc in enrollment_cursor]
        if not student_ids:
            return []

        student_cursor = self.db["students"].find(
            {"academy_id": academy_id, "student_id": {"$in": student_ids}},
            {"parent_id": 1, "parent_user_id": 1},
        )
        parent_ids: set[str] = set()
        async for doc in student_cursor:
            pid = doc.get("parent_id") or doc.get("parent_user_id")
            if pid:
                parent_ids.add(str(pid))

        if not parent_ids:
            return []

        user_cursor = self.db["users"].find(
            {"academy_id": academy_id, "user_id": {"$in": list(parent_ids)}},
            {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        return [self._user_to_recipient(doc) async for doc in user_cursor]

    async def resolve_coach_audience(self, audience: CoachAudience) -> list[ResolvedRecipient]:
        if audience.session_id:
            return await self.resolve_session_audience(
                SessionAudience(session_id=audience.session_id)
            )
        return await self.resolve_academy_audience(AcademyAudience(role="coach"))

    async def resolve_selected_audience(
        self, audience: SelectedRecipientsAudience
    ) -> list[ResolvedRecipient]:
        academy_id = current_academy_id()
        cursor = self.db["users"].find(
            {"academy_id": academy_id, "user_id": {"$in": list(audience.user_ids)}},
            {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        return [self._user_to_recipient(doc) async for doc in cursor]

    async def resolve_payment_risk_audience(
        self, audience: PaymentRiskAudience
    ) -> list[ResolvedRecipient]:
        from datetime import UTC, datetime, timedelta

        academy_id = current_academy_id()
        cutoff = datetime.now(UTC) - timedelta(days=audience.min_days_overdue)
        cursor = self.db["payments"].find(
            {"academy_id": academy_id, "status": "pending", "due_date": {"$lt": cutoff}},
            {"user_id": 1},
        )
        user_ids = list({str(doc["user_id"]) async for doc in cursor})
        if not user_ids:
            return []
        user_cursor = self.db["users"].find(
            {"academy_id": academy_id, "user_id": {"$in": user_ids}},
            {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        return [self._user_to_recipient(doc) async for doc in user_cursor]

    @staticmethod
    def _user_to_recipient(doc: dict[str, Any]) -> ResolvedRecipient:
        return ResolvedRecipient(
            user_id=str(doc.get("user_id") or doc.get("_id")),
            email=doc.get("email"),
            display_name=doc.get("display_name") or doc.get("name"),
        )
