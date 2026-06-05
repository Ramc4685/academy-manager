"""MongoDB implementation of ProgramRepository."""

from __future__ import annotations

from backend.v2.contexts.curriculum.domain.models import Program
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoProgramRepository(TenantScopedRepository):
    collection_name = "skill_programs"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Program:
        return Program(
            program_id=str(doc["program_id"]),
            academy_id=str(doc["academy_id"]),
            sport=str(doc["sport"]),
            name=str(doc["name"]),
            description=str(doc.get("description", "")),
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
            created_by=str(doc.get("created_by", "")),
        )

    async def save(self, program: Program) -> None:
        await self._insert_one(
            {
                "program_id": program.program_id,
                "sport": program.sport,
                "name": program.name,
                "description": program.description,
                "is_active": program.is_active,
                "created_at": program.created_at,
                "updated_at": program.updated_at,
                "created_by": program.created_by,
            }
        )

    async def get(self, program_id: str) -> Program | None:
        doc = await self._find_one({"program_id": program_id})
        return self._to_domain(doc) if doc else None

    async def list_active(self) -> list[Program]:
        cursor = self._find_many({"is_active": True}, sort=[("created_at", 1)])
        return [self._to_domain(doc) async for doc in cursor]
