"""Mongo-backed WaiverTemplate repository.

Templates are immutable once active. This repo only supports ``get`` (by id)
and ``get_active`` (most-recent active template, if any). Publishing /
superseding flows belong in a dedicated admin use case which is not part of
this Wave 4 prep slice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId as BsonObjectId
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
    WaiverVersionConflict,
)
from backend.v2.contexts.onboarding.domain.models import WaiverTemplate
from backend.v2.contexts.onboarding.domain.waiver_assignment import (
    WaiverAssignment,
    assignment_from_document,
    lineage_of,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_program_lookup import (
    MongoWaiverProgramLookup,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

#: The raw ``waiver_templates.status`` spellings that mean "this row can be the
#: academy's live waiver". ``active`` is what :meth:`publish_draft` writes;
#: ``published`` is the older production spelling that ``_template_status``
#: normalises to ``active`` on read. Both readers — the registration lookup
#: here and the parent prompt in ``mongo_parent_waiver_repo`` — share this set,
#: because when they disagreed (issue #785) a ``published`` row was required at
#: registration and invisible to the parent who had to sign it.
LIVE_TEMPLATE_STATUSES: tuple[str, ...] = ("active", "published")


class MongoWaiverTemplateRepository(TenantScopedRepository):
    collection_name = "waiver_templates"

    @staticmethod
    def _as_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                return None
        return None

    @classmethod
    def _to_domain(cls, doc: dict[str, Any]) -> WaiverTemplate:
        effective_from = cls._as_datetime(
            doc.get("effective_from")
            or doc.get("published_at")
            or doc.get("assigned_at")
            or doc.get("updated_at")
            or doc.get("created_at")
        )
        if effective_from is None:
            raise ValueError(
                f"waiver_templates row {doc.get('waiver_template_id')!r} is missing effective_from"
            )
        return WaiverTemplate(
            waiver_template_id=str(doc.get("waiver_template_id") or doc.get("_id")),
            academy_id=str(doc["academy_id"]),
            name=str(doc.get("name") or ""),
            version=str(doc["version"]),
            content_hash=str(doc["content_hash"]),
            body=str(doc.get("body") or ""),
            effective_from=effective_from,
            expires_at=cls._as_datetime(doc.get("expires_at")),
            status=cls._template_status(doc),
        )

    @classmethod
    def _to_record(cls, doc: dict[str, Any]) -> AdminWaiverTemplateRecord:
        updated_at = cls._as_datetime(doc.get("updated_at") or doc.get("created_at"))
        if updated_at is None:
            updated_at = datetime.now(UTC)
        assignment = assignment_from_document(doc)
        return AdminWaiverTemplateRecord(
            lineage_key=lineage_of(doc),
            required=assignment.required,
            scope=assignment.scope,
            program_ids=list(assignment.program_ids),
            waiver_template_id=str(doc.get("waiver_template_id") or doc.get("_id")),
            title=str(doc.get("name") or doc.get("title") or ""),
            body=str(doc.get("body") or doc.get("text") or doc.get("waiver_text") or ""),
            status=cls._template_status(doc),
            version=(str(doc["version"]) if doc.get("version") is not None else None),
            content_hash=(
                str(doc["content_hash"]) if doc.get("content_hash") is not None else None
            ),
            effective_from=cls._as_datetime(
                doc.get("effective_from")
                or doc.get("published_at")
                or doc.get("assigned_at")
                or doc.get("updated_at")
                or doc.get("created_at")
            ),
            published_at=cls._as_datetime(doc.get("published_at")),
            assigned_to_registration=bool(doc.get("assigned_to_registration") or False),
            assigned_at=cls._as_datetime(doc.get("assigned_at")),
            updated_at=updated_at,
        )

    @staticmethod
    def _template_status(doc: dict[str, Any]) -> str:
        status = str(doc.get("status") or "active")
        if status == "published":
            return "active"
        return status

    async def _find_by_id(self, waiver_template_id: str) -> dict[str, Any] | None:
        """The template by ``waiver_template_id``, else by legacy ``_id``.

        Two equality lookups, not one ``$or``: the first is served by the
        per-academy id index, while MongoDB 8.0 (production) scans the
        academy's templates for the ``$or`` form (#878, #894). Only ids that
        are valid ObjectId hex get the second, legacy, lookup.
        """
        doc = await self._find_one({"waiver_template_id": waiver_template_id})
        if doc is None and BsonObjectId.is_valid(waiver_template_id):
            doc = await self._find_one({"_id": BsonObjectId(waiver_template_id)})
        return doc

    @staticmethod
    def _to_draft_document(template: AdminWaiverTemplateRecord) -> dict[str, Any]:
        return {
            "waiver_template_id": template.waiver_template_id,
            "name": template.title,
            "body": template.body,
            "status": template.status,
            "version": template.version,
            "content_hash": template.content_hash,
            "effective_from": template.effective_from,
            "published_at": template.published_at,
            "assigned_to_registration": template.assigned_to_registration,
            "assigned_at": template.assigned_at,
            "updated_at": template.updated_at,
            "lineage_key": template.lineage,
        }

    async def get(self, waiver_template_id: str) -> WaiverTemplate | None:
        doc = await self._find_by_id(waiver_template_id)
        return self._to_domain(doc) if doc else None

    async def get_active(self) -> WaiverTemplate | None:
        cursor = self._find_many(
            {"status": "active"},
            sort=[("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None

    async def get_registration_template(self) -> AdminWaiverTemplateRecord | None:
        cursor = self._find_many(
            {"status": {"$in": list(LIVE_TEMPLATE_STATUSES)}, "assigned_to_registration": True},
            sort=[("assigned_at", -1), ("effective_from", -1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_record(doc)
        return None

    async def program_id_for_session(self, session_id: str | None) -> str | None:
        return await MongoWaiverProgramLookup(self._db).program_id_for_session(session_id)

    async def list_required_templates(self) -> list[AdminWaiverTemplateRecord]:
        """Every live waiver families must sign (all-family or program-scoped).

        One query for the academy's live rows; the assignment (with its
        read-time default for rows that only carry ``assigned_to_registration``)
        is applied here, never in a Mongo filter, so an old row and a new row
        are read the same way. Newest assignment first, so the first entry is
        the "primary" registration waiver a single-waiver academy has today.
        """
        docs = [
            doc
            async for doc in self._find_many(
                {"status": {"$in": list(LIVE_TEMPLATE_STATUSES)}},
                sort=[("assigned_at", -1), ("effective_from", -1)],
            )
        ]
        return [self._to_record(doc) for doc in docs if assignment_from_document(doc).required]

    async def list_templates(self) -> list[AdminWaiverTemplateRecord]:
        cursor = self._find_many(sort=[("updated_at", -1)])
        return [self._to_record(doc) async for doc in cursor]

    async def create_draft(self, template: AdminWaiverTemplateRecord) -> AdminWaiverTemplateRecord:
        await self._insert_one(self._to_draft_document(template))
        stored = await self.get_template(template.waiver_template_id)
        if stored is None:
            raise RuntimeError("Failed to store waiver template draft")
        return stored

    async def get_template(self, waiver_template_id: str) -> AdminWaiverTemplateRecord | None:
        doc = await self._find_by_id(waiver_template_id)
        return self._to_record(doc) if doc else None

    async def publish_draft(
        self,
        *,
        waiver_template_id: str,
        version: str,
        content_hash: str,
        published_at: datetime,
    ) -> AdminWaiverTemplateRecord:
        academy_id = current_academy_id()
        draft = await self._find_by_id(waiver_template_id)
        lineage = lineage_of(draft) if draft is not None else lineage_of({})
        # Publishing supersedes only the live rows of the SAME lineage: another
        # waiver stays live (Settings Phase 6). The lineage is compared in
        # Python, not in a Mongo filter, so a legacy row with no key and a row
        # carrying "legacy" are one lineage and no ``$or`` is needed.
        live_docs = [
            doc async for doc in self._find_many({"status": {"$in": list(LIVE_TEMPLATE_STATUSES)}})
        ]
        superseded_docs = [
            doc
            for doc in live_docs
            if lineage_of(doc) == lineage
            and doc.get("waiver_template_id") != waiver_template_id
            and (draft is None or doc.get("_id") != draft.get("_id"))
        ]
        # Issue #785: ``assigned_to_registration`` marks "the waiver this
        # academy asks new families to sign" — a property of the waiver, not of
        # one version. Carry the assignment (flag, scope, programs) onto the
        # version being published and clear the flag on the rows it supersedes,
        # so exactly one row per lineage ever claims it.
        inherits_registration = any(doc.get("assigned_to_registration") for doc in superseded_docs)
        inherited_assignment = self._inherited_assignment(superseded_docs)
        published_fields: dict[str, Any] = {
            "status": "active",
            "version": version,
            "content_hash": content_hash,
            "effective_from": published_at,
            "published_at": published_at,
            "updated_at": published_at,
            "lineage_key": lineage,
        }
        if inherits_registration:
            published_fields["assigned_to_registration"] = True
            published_fields["assigned_at"] = published_at
        if inherited_assignment is not None:
            published_fields.update(self._assignment_fields(inherited_assignment))
        if draft is not None:
            # Publish the draft FIRST, then supersede. If the write fails (the
            # version is taken, e.g. the old (academy, version) index before
            # migration 0211, or another admin published this draft), the
            # currently live waiver is untouched instead of left superseded
            # with nothing live in its place.
            try:
                result = await self.collection.update_one(
                    {"academy_id": academy_id, "_id": draft["_id"], "status": "draft"},
                    {"$set": published_fields},
                )
            except DuplicateKeyError as exc:
                raise WaiverVersionConflict(
                    "That waiver version already exists. Refresh and try again."
                ) from exc
            if result.matched_count == 0:
                raise WaiverVersionConflict("This draft was already published. Refresh the page.")
        if superseded_docs:
            await self.collection.update_many(
                {"academy_id": academy_id, "_id": {"$in": [doc["_id"] for doc in superseded_docs]}},
                {
                    "$set": {
                        "status": "superseded",
                        "assigned_to_registration": False,
                        "updated_at": published_at,
                    }
                },
            )
        published = await self.get_template(waiver_template_id)
        if published is None:
            raise RuntimeError("Failed to publish waiver template draft")
        return published

    @staticmethod
    def _inherited_assignment(superseded: list[dict[str, Any]]) -> WaiverAssignment | None:
        """The explicit assignment of the newest superseded row, if it had one.

        Rows that only carry the old registration flag return ``None``: the
        flag is carried on its own and reads back as required for all families.
        """
        explicit = [doc for doc in superseded if doc.get("required") is not None]
        if not explicit:
            return None
        newest = max(
            explicit,
            key=lambda doc: (
                MongoWaiverTemplateRepository._as_datetime(
                    doc.get("effective_from") or doc.get("updated_at")
                )
                or datetime.min.replace(tzinfo=UTC)
            ),
        )
        return assignment_from_document(newest)

    @staticmethod
    def _assignment_fields(assignment: WaiverAssignment) -> dict[str, Any]:
        return {
            "required": assignment.required,
            "scope": assignment.scope,
            "program_ids": list(assignment.program_ids),
            "assigned_to_registration": assignment.for_all_families,
        }

    async def assign_to_registration(
        self,
        *,
        waiver_template_id: str,
        assigned_at: datetime,
    ) -> AdminWaiverTemplateRecord:
        """Legacy "require for registration": required for all families.

        Other waivers keep their own assignment; only the older rows of this
        waiver's lineage (already superseded, or about to be) lose the flag.
        """
        return await self.set_assignment(
            waiver_template_id=waiver_template_id,
            assignment=WaiverAssignment(required=True, scope="all"),
            assigned_at=assigned_at,
        )

    async def set_assignment(
        self,
        *,
        waiver_template_id: str,
        assignment: WaiverAssignment,
        assigned_at: datetime,
    ) -> AdminWaiverTemplateRecord:
        academy_id = current_academy_id()
        template = await self._find_by_id(waiver_template_id)
        if template is not None:
            lineage = lineage_of(template)
            # A lineage never has two live rows, but old data may: only the
            # row being assigned keeps the registration flag within its lineage.
            siblings = [
                doc["_id"]
                async for doc in self._find_many({"assigned_to_registration": True})
                if lineage_of(doc) == lineage and doc["_id"] != template["_id"]
            ]
            if siblings:
                await self.collection.update_many(
                    {"academy_id": academy_id, "_id": {"$in": siblings}},
                    {
                        "$set": {
                            "assigned_to_registration": False,
                            "assigned_at": None,
                            "updated_at": assigned_at,
                        }
                    },
                )
        fields = self._assignment_fields(assignment)
        fields["assigned_at"] = assigned_at if assignment.for_all_families else None
        fields["updated_at"] = assigned_at
        await self._update_one(
            {
                "_id": template["_id"] if template is not None else None,
                "status": {"$in": list(LIVE_TEMPLATE_STATUSES)},
            },
            {"$set": fields},
        )
        assigned = await self.get_template(waiver_template_id)
        if assigned is None:
            raise RuntimeError("Failed to assign waiver template")
        return assigned
