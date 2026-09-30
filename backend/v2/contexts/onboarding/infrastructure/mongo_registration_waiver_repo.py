"""Mongo WaiverRepository for the parent registration stepper.

Resolves the waiver template that is active/published AND assigned to registration
by an admin (assigned_to_registration == True). Returns None when no such
template exists — PatchApplication raises NoActiveWaiver in that case.

Maps WaiverTemplate fields → legacy Waiver domain shape so PatchApplication
needs no change. The waiver_id on the returned Waiver equals the source
waiver_template_id, allowing WaiverAcceptance to pin the audit link.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from backend.v2.contexts.onboarding.domain.models import Waiver
from backend.v2.contexts.onboarding.domain.waiver_assignment import (
    assignment_from_document,
    lineage_of,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_program_lookup import (
    MongoWaiverProgramLookup,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_template_repo import (
    LIVE_TEMPLATE_STATUSES,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoRegistrationWaiverRepository(TenantScopedRepository):
    collection_name = "waiver_templates"

    @staticmethod
    def _as_datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        raise ValueError(f"Cannot parse datetime from {value!r}")

    @classmethod
    def _to_domain(cls, doc: dict[str, Any]) -> Waiver:
        text = str(doc.get("body") or doc.get("text") or doc.get("waiver_text") or "")
        content_hash = doc.get("content_hash") or sha256(text.encode("utf-8")).hexdigest()
        effective_from = (
            doc.get("effective_from")
            or doc.get("published_at")
            or doc.get("assigned_at")
            or doc.get("updated_at")
        )
        return Waiver(
            waiver_id=str(doc.get("waiver_template_id") or doc.get("waiver_id") or doc["_id"]),
            academy_id=str(doc["academy_id"]),
            version=str(doc["version"]),
            text=text,
            content_hash=str(content_hash),
            effective_from=cls._as_datetime(effective_from),
            lineage_key=lineage_of(doc),
            title=(str(doc.get("name") or doc.get("title") or "") or None),
        )

    async def list_required(self, session_id: str | None) -> list[Waiver]:
        """The waivers a family signs for this class.

        Every live waiver required for all families, plus every live waiver
        assigned to the program the class sits in. With one all-families waiver
        (BLNO today) this is exactly ``[get_active()]``. When nothing is
        assigned at all, the pre-assignment fallback in :meth:`get_active` still
        applies, so an academy that never assigned a waiver behaves as before.
        """
        docs = [
            doc
            async for doc in self._find_many(
                {"status": {"$in": list(LIVE_TEMPLATE_STATUSES)}},
                sort=[("assigned_at", -1), ("effective_from", -1)],
            )
        ]
        assigned = [(doc, assignment_from_document(doc)) for doc in docs]
        program_id = await MongoWaiverProgramLookup(self._db).program_id_for_session(session_id)
        chosen = [
            doc
            for doc, assignment in assigned
            if assignment.for_all_families or (program_id and assignment.applies_to([program_id]))
        ]
        # All-family waivers first (primary = newest assignment), then the
        # program's, so the primary waiver is the same one a single-waiver
        # academy has always had.
        chosen.sort(key=lambda doc: 0 if assignment_from_document(doc).for_all_families else 1)
        if chosen:
            return [self._to_domain(doc) for doc in chosen]
        fallback = await self.get_active()
        return [fallback] if fallback is not None else []

    async def has_program_scoped_waivers(self) -> bool:
        cursor = self._find_many({"status": {"$in": list(LIVE_TEMPLATE_STATUSES)}})
        async for doc in cursor:
            assignment = assignment_from_document(doc)
            if assignment.required and assignment.scope == "programs":
                return True
        return False

    async def get_active(self) -> Waiver | None:
        cursor = self._find_many(
            {"status": {"$in": ["active", "published"]}, "assigned_to_registration": True},
            sort=[("assigned_at", -1), ("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)

        cursor = self._find_many(
            {
                "status": "published",
                "body": {"$type": "string", "$ne": ""},
                "assigned_to_registration": {"$exists": False},
            },
            sort=[("published_at", -1), ("effective_from", -1), ("updated_at", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None
