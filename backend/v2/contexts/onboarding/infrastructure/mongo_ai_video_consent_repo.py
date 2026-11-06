"""Mongo-backed per-child AI/video consent (``ai_video_consents``).

One row per (academy, student) holding the current state, plus an
append-only ``history`` of every grant and revocation, so a re-grant never
erases the record that consent was once withdrawn.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.onboarding.application.use_cases.ai_video_consent import (
    AiVideoConsentChild,
)
from backend.v2.contexts.onboarding.domain.ai_video_consent import AiVideoConsent
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


def _to_consent(doc: dict[str, Any]) -> AiVideoConsent:
    return AiVideoConsent(
        student_id=str(doc["student_id"]),
        status=doc.get("status", "revoked"),
        text_version=str(doc.get("text_version") or ""),
        accepted_at=_aware(doc.get("accepted_at")) or datetime.min.replace(tzinfo=UTC),
        accepted_by=str(doc.get("accepted_by") or ""),
        accepted_by_email=doc.get("accepted_by_email"),
        revoked_at=_aware(doc.get("revoked_at")),
        revoked_by=doc.get("revoked_by"),
    )


def _student_name(doc: dict[str, Any]) -> str:
    name = str(doc.get("full_name") or "").strip()
    if name:
        return name
    return " ".join(
        part for part in (doc.get("first_name"), doc.get("last_name")) if part
    ).strip() or str(doc.get("student_id") or doc.get("_id"))


class MongoAiVideoConsentRepository(TenantScopedRepository):
    collection_name = "ai_video_consents"

    async def children_of(self, parent_id: str) -> list[AiVideoConsentChild]:
        # Same ownership read as the parent waiver page (parent_id or
        # parent_user_id), without its live-enrollment or active-status filter: a parent can
        # still see and revoke consent for a child between classes or after they leave.
        academy_id = current_academy_id()
        seen: dict[str, AiVideoConsentChild] = {}
        for field in ("parent_id", "parent_user_id"):
            async for doc in self._db["students"].find(
                {
                    "academy_id": academy_id,
                    "is_deleted": {"$ne": True},
                    field: parent_id,
                },
                sort=[("full_name", 1)],
            ):
                student_id = str(doc.get("student_id") or doc.get("_id"))
                seen.setdefault(
                    student_id,
                    AiVideoConsentChild(student_id=student_id, student_name=_student_name(doc)),
                )
        return list(seen.values())

    async def consents_for(self, student_ids: list[str]) -> dict[str, AiVideoConsent]:
        if not student_ids:
            return {}
        cursor = self.collection.find(self._scoped({"student_id": {"$in": student_ids}}))
        return {str(doc["student_id"]): _to_consent(doc) async for doc in cursor}

    async def save_grant(self, consent: AiVideoConsent) -> None:
        await self.collection.update_one(
            self._scoped({"student_id": consent.student_id}),
            {
                "$set": {
                    "status": "granted",
                    "text_version": consent.text_version,
                    "accepted_at": consent.accepted_at,
                    "accepted_by": consent.accepted_by,
                    "accepted_by_email": consent.accepted_by_email,
                    "revoked_at": None,
                    "revoked_by": None,
                },
                "$push": {
                    "history": {
                        "action": "granted",
                        "text_version": consent.text_version,
                        "at": consent.accepted_at,
                        "by": consent.accepted_by,
                    }
                },
                "$setOnInsert": {"academy_id": current_academy_id()},
            },
            upsert=True,
        )

    async def save_revoke(self, student_id: str, *, revoked_at: datetime, revoked_by: str) -> None:
        await self.collection.update_one(
            self._scoped({"student_id": student_id, "status": "granted"}),
            {
                "$set": {"status": "revoked", "revoked_at": revoked_at, "revoked_by": revoked_by},
                "$push": {"history": {"action": "revoked", "at": revoked_at, "by": revoked_by}},
            },
        )

    async def list_all(self) -> list[tuple[AiVideoConsent, str]]:
        consents = [_to_consent(doc) async for doc in self.collection.find(self._scoped({}))]
        if not consents:
            return []
        ids = [consent.student_id for consent in consents]
        names: dict[str, str] = {}
        async for doc in self._db["students"].find(
            {"academy_id": current_academy_id(), "student_id": {"$in": ids}}
        ):
            names[str(doc["student_id"])] = _student_name(doc)
        return [
            (consent, names.get(consent.student_id, consent.student_id)) for consent in consents
        ]

    async def get_for_academy(self, academy_id: str, student_id: str) -> AiVideoConsent | None:
        doc = await self.collection.find_one({"academy_id": academy_id, "student_id": student_id})
        return _to_consent(doc) if doc else None
