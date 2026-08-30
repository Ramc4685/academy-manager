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

    def _membership_role_filter(self, role: str) -> dict[str, Any]:
        return {
            "academy_id": current_academy_id(),
            "status": "active",
            "$or": [{"role": role}, {"roles": role}],
        }

    async def _resolve_users_for_ids(self, user_ids: list[str]) -> list[ResolvedRecipient]:
        """Fetch user docs for ids, scoped to the current academy.

        The users collection holds one doc per (user, academy) for
        multi-academy users, plus legacy global docs without academy_id.
        Match the current tenant's doc or a global doc — never another
        academy's — and dedupe by user_id, preferring the tenant-scoped
        doc so its email/display name wins over a global fallback.
        """
        academy_id = current_academy_id()
        cursor = self.db["users"].find(
            {
                "academy_id": {"$in": [academy_id, None]},
                "$or": [{"user_id": {"$in": user_ids}}, {"auth_uid": {"$in": user_ids}}],
            },
            {"user_id": 1, "academy_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        best: dict[str, dict[str, Any]] = {}
        async for doc in cursor:
            key = str(doc.get("user_id") or doc.get("_id"))
            existing = best.get(key)
            if existing is None or (
                existing.get("academy_id") != academy_id and doc.get("academy_id") == academy_id
            ):
                best[key] = doc
        return [self._user_to_recipient(doc) for doc in best.values()]

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        membership_cursor = self.db["academy_memberships"].find(
            self._membership_role_filter(audience.role),
            {"user_id": 1},
        )
        user_ids = [str(doc["user_id"]) async for doc in membership_cursor if doc.get("user_id")]
        if user_ids:
            return await self._resolve_users_for_ids(user_ids)

        legacy_cursor = self.db["users"].find(
            self._role_filter(audience.role),
            {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
        )
        return [self._user_to_recipient(doc) async for doc in legacy_cursor]

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
            academy_id = current_academy_id()
            session_doc = await self.db["sessions"].find_one(
                {"academy_id": academy_id, "session_id": audience.session_id},
                {"coach_id": 1},
            )
            if not session_doc or not session_doc.get("coach_id"):
                return []
            coach_id = str(session_doc["coach_id"])
            user_doc = await self.db["users"].find_one(
                {
                    "academy_id": academy_id,
                    "$or": [{"user_id": coach_id}, {"auth_uid": coach_id}],
                },
                {"user_id": 1, "email": 1, "display_name": 1, "name": 1},
            )
            if not user_doc:
                return []
            return [self._user_to_recipient(user_doc)]
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
        invoice_cursor = self.db["invoices"].find(
            {
                "academy_id": academy_id,
                # Only payable statuses: draft invoices are excluded because the
                # parent checkout/digest paths treat only open/partially_paid as
                # payable — emailing about a draft balance would 404 the pay flow.
                "status": {"$in": ["open", "partially_paid"]},
                "balance_due_cents": {"$gt": 0},
                "due_date": {"$lt": cutoff},
                "is_deleted": {"$ne": True},
            },
            {"parent_id": 1, "parent_user_id": 1},
        )
        user_ids = list(
            {
                str(doc.get("parent_id") or doc.get("parent_user_id"))
                async for doc in invoice_cursor
                if doc.get("parent_id") or doc.get("parent_user_id")
            }
        )
        if not user_ids:
            cursor = self.db["payments"].find(
                {"academy_id": academy_id, "status": "pending", "due_date": {"$lt": cutoff}},
                {"user_id": 1},
            )
            user_ids = list({str(doc["user_id"]) async for doc in cursor if doc.get("user_id")})
        if not user_ids:
            return []
        # Every id here came from this academy's overdue invoices/payments, so
        # the set is already tenant-scoped. Resolve them all: narrowing to
        # active parent memberships would silently drop delinquent parents who
        # have a tenant-scoped (or legacy global) user doc but no active
        # academy_memberships doc — the issue asked for de-duplication and
        # academy scoping, not for excluding membership-less tenant users.
        # _resolve_users_for_ids keeps the cross-tenant fix: it only matches
        # the current academy's doc or a global doc, never another tenant's.
        return await self._resolve_users_for_ids(user_ids)

    @staticmethod
    def _user_to_recipient(doc: dict[str, Any]) -> ResolvedRecipient:
        return ResolvedRecipient(
            user_id=str(doc.get("user_id") or doc.get("_id")),
            email=doc.get("email"),
            display_name=doc.get("display_name") or doc.get("name"),
        )
