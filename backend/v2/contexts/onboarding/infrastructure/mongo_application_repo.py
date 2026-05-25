"""Mongo ApplicationRepository."""

from __future__ import annotations

from backend.v2.contexts.onboarding.domain.models import (
    Application,
    ChildProfile,
    ParentProfile,
    WaiverAcceptance,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoApplicationRepository(TenantScopedRepository):
    collection_name = "onboarding_applications"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Application:
        wa = doc.get("waiver_acceptance")
        return Application(
            application_id=str(doc["application_id"]),
            academy_id=str(doc["academy_id"]),
            parent_user_id=str(doc["parent_user_id"]),
            parent_email=str(doc["parent_email"]),
            status=doc.get("status", "DRAFT"),  # type: ignore[arg-type]
            parent_profile=ParentProfile.model_validate(doc.get("parent_profile") or {}),
            child_profile=ChildProfile.model_validate(doc.get("child_profile") or {}),
            selected_session_id=doc.get("selected_session_id"),  # type: ignore[arg-type]
            waiver_acceptance=WaiverAcceptance.model_validate(wa) if wa else None,
            stripe_checkout_session_id=doc.get("stripe_checkout_session_id"),  # type: ignore[arg-type]
            payment_id=doc.get("payment_id"),  # type: ignore[arg-type]
            student_id=doc.get("student_id"),  # type: ignore[arg-type]
            enrollment_id=doc.get("enrollment_id"),  # type: ignore[arg-type]
            waitlist_id=doc.get("waitlist_id"),  # type: ignore[arg-type]
            decision_reason=doc.get("decision_reason"),  # type: ignore[arg-type]
            decided_by=doc.get("decided_by"),  # type: ignore[arg-type]
            decided_at=doc.get("decided_at"),  # type: ignore[arg-type]
            expires_at=doc["expires_at"],  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
        )

    async def save(self, app: Application) -> None:
        doc = app.model_dump(mode="python")
        await self._update_one(
            {"application_id": app.application_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, application_id: str) -> Application | None:
        doc = await self._find_one({"application_id": application_id})
        return self._to_domain(doc) if doc else None

    async def latest_for_parent(self, parent_user_id: str) -> Application | None:
        cursor = self._find_many(
            {"parent_user_id": parent_user_id},
            sort=[("created_at", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None

    async def get_by_payment_id(self, payment_id: str) -> Application | None:
        doc = await self._find_one({"payment_id": payment_id})
        return self._to_domain(doc) if doc else None

    async def list_by_status(self, statuses: list[str]) -> list[Application]:
        cursor = self._find_many(
            {"status": {"$in": statuses}},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
