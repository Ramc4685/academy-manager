"""MongoDB implementation of LevelRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.curriculum.domain.errors import DuplicateSequence
from backend.v2.contexts.curriculum.domain.models import Level
from backend.v2.shared.tenancy import TenantScopedRepository


class SequencedRepository(TenantScopedRepository):
    """Shared numbering for levels and skills (unique sequence index, 0120)."""

    id_field: str

    async def _next_sequence(self, scope: dict[str, object]) -> int:
        """One past the highest sequence in ``scope``, retired rows included."""
        cursor = self._find_many(scope, sort=[("sequence", -1)], limit=1)
        top = [int(doc["sequence"]) async for doc in cursor]
        return (top[0] if top else 0) + 1

    async def _insert_sequenced(self, doc: dict[str, object]) -> None:
        try:
            await self._insert_one(doc)
        except DuplicateKeyError as exc:  # a concurrent create took the number
            raise DuplicateSequence(
                "another item took that position; try again", sequence=doc.get("sequence")
            ) from exc

    async def resequence(self, ordered_ids: list[str]) -> None:
        """Number ``ordered_ids`` 1..n in two passes, so the unique sequence
        index never sees two rows on one number mid-way. Pass one lifts every
        row above the current highest, so a retry after a crash (or a reorder
        racing this one) starts from a free range instead of colliding again.

        shortcut: not atomic; a crash between passes leaves sequences high
        (still ordered) until the next reorder.
        """
        cursor = self._find_many(
            {self.id_field: {"$in": ordered_ids}}, sort=[("sequence", -1)], limit=1
        )
        top = [int(doc["sequence"]) async for doc in cursor]
        lift = (top[0] if top else 0) + 1
        now = datetime.now(UTC)
        for i, item_id in enumerate(ordered_ids):
            await self._update_one({self.id_field: item_id}, {"$set": {"sequence": lift + i}})
        for i, item_id in enumerate(ordered_ids, start=1):
            await self._update_one(
                {self.id_field: item_id}, {"$set": {"sequence": i, "updated_at": now}}
            )


class MongoLevelRepository(SequencedRepository):
    collection_name = "skill_levels"
    id_field = "level_id"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Level:
        return Level(
            level_id=str(doc["level_id"]),
            program_id=str(doc["program_id"]),
            academy_id=str(doc["academy_id"]),
            sequence=int(doc["sequence"]),
            name=str(doc["name"]),
            description=str(doc.get("description", "")),
            completion_rule=doc.get("completion_rule", "ALL_REQUIRED_SKILLS"),
            points_threshold=doc.get("points_threshold"),
            requires_coach_recommendation=bool(doc.get("requires_coach_recommendation", True)),
            requires_admin_approval=bool(doc.get("requires_admin_approval", False)),
            color=doc.get("color") or None,
            is_active=bool(doc.get("is_active", True)),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            created_by=str(doc.get("created_by", "")),
        )

    async def save(self, level: Level) -> None:
        await self._insert_sequenced(
            {
                "level_id": level.level_id,
                "program_id": level.program_id,
                "sequence": level.sequence,
                "name": level.name,
                "description": level.description,
                "completion_rule": level.completion_rule,
                "points_threshold": level.points_threshold,
                "requires_coach_recommendation": level.requires_coach_recommendation,
                "requires_admin_approval": level.requires_admin_approval,
                "color": level.color,
                "is_active": level.is_active,
                "created_at": level.created_at,
                "updated_at": level.updated_at,
                "created_by": level.created_by,
            }
        )

    async def update(self, level: Level) -> None:
        await self._update_one(
            {"level_id": level.level_id},
            {
                "$set": {
                    "name": level.name,
                    "description": level.description,
                    "completion_rule": level.completion_rule,
                    "requires_coach_recommendation": level.requires_coach_recommendation,
                    "requires_admin_approval": level.requires_admin_approval,
                    "color": level.color,
                    "is_active": level.is_active,
                    "updated_at": level.updated_at,
                }
            },
        )

    async def get(self, level_id: str) -> Level | None:
        doc = await self._find_one({"level_id": level_id})
        return self._to_domain(doc) if doc else None

    async def list_for_program(self, program_id: str) -> list[Level]:
        cursor = self._find_many(
            {"program_id": program_id, "is_active": True},
            sort=[("sequence", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_all_for_program(self, program_id: str) -> list[Level]:
        """Active and retired levels, in sequence order (reorder needs both)."""
        cursor = self._find_many({"program_id": program_id}, sort=[("sequence", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def next_sequence(self, program_id: str) -> int:
        return await self._next_sequence({"program_id": program_id})
