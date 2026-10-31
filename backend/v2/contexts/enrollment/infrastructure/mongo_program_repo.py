"""Mongo repository for ``programs`` (public tenant page, Lane B1; migration 0194)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pydantic import ValidationError

from backend.v2.contexts.enrollment.domain.programs import AgeBand, Program
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import ensure_utc

#: Written by ``save``; ``program_id``, ``academy_id`` and ``created_at``
#: never change after insert.
_MUTABLE = ("name", "public_description", "level", "age_band", "sort_order", "archived")


class MongoProgramRepository(TenantScopedRepository):
    collection_name = "programs"

    @staticmethod
    def _to_doc(program: Program) -> dict[str, Any]:
        doc = program.model_dump(mode="python")
        # Never trust a caller-built academy_id: the tenant context owns it.
        doc["academy_id"] = current_academy_id()
        return doc

    @staticmethod
    def to_domain(doc: dict[str, Any]) -> Program:
        return Program(
            program_id=str(doc["program_id"]),
            academy_id=str(doc["academy_id"]),
            name=str(doc.get("name") or "Program"),
            public_description=doc.get("public_description"),
            level=doc.get("level"),
            age_band=_age_band(doc.get("age_band")),
            sort_order=int(doc.get("sort_order") or 0),
            archived=bool(doc.get("archived", False)),
            created_at=_utc(doc["created_at"]),
            updated_at=_utc(doc.get("updated_at") or doc["created_at"]),
        )

    async def add(self, program: Program) -> Program:
        doc = self._to_doc(program)
        await self._insert_one(doc)
        return self.to_domain(doc)

    async def get(self, program_id: str) -> Program | None:
        doc = await self._find_one({"program_id": program_id})
        return self.to_domain(doc) if doc else None

    async def list_all(self, *, include_archived: bool = False) -> list[Program]:
        query: dict[str, Any] = {} if include_archived else {"archived": {"$ne": True}}
        cursor = self._find_many(query, sort=[("sort_order", 1)])
        return [self.to_domain(doc) async for doc in cursor]

    async def save(self, program: Program) -> Program | None:
        doc = self._to_doc(program)
        fields = {key: doc[key] for key in _MUTABLE}
        fields["updated_at"] = doc["updated_at"]
        stored = await self._find_one_and_update(
            {"program_id": program.program_id}, {"$set": fields}
        )
        return self.to_domain(stored) if stored else None


def _age_band(value: object) -> AgeBand | None:
    if not isinstance(value, dict):
        return None
    try:
        return AgeBand(min_age=value.get("min_age"), max_age=value.get("max_age"))
    except ValidationError:
        return None


def _utc(value: object) -> datetime:
    return ensure_utc(cast(datetime, value))
