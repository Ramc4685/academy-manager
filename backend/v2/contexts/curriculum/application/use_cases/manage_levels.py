"""Curriculum use cases: level management."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.curriculum.application.ports import (
    LevelDeletionStore,
    LevelRepository,
    ProgramRepository,
)
from backend.v2.contexts.curriculum.domain.errors import (
    InvalidOrder,
    LevelInUse,
    LevelNotFound,
    ProgramNotFound,
)
from backend.v2.contexts.curriculum.domain.models import (
    HEX_COLOR_PATTERN,
    Level,
    LevelCompletionRule,
)
from backend.v2.shared.ids import new_ulid


class CreateLevelCommand(BaseModel):
    model_config = {"frozen": True}
    program_id: str
    name: str
    description: str = ""
    completion_rule: LevelCompletionRule = "ALL_REQUIRED_SKILLS"
    requires_coach_recommendation: bool = True
    requires_admin_approval: bool = False
    created_by: str


class UpdateLevelCommand(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    name: str | None = None
    description: str | None = None
    completion_rule: LevelCompletionRule | None = None
    requires_coach_recommendation: bool | None = None
    requires_admin_approval: bool | None = None
    #: A hex colour, ``""`` to go back to the level's default, ``None`` to keep.
    color: str | None = Field(default=None, pattern=f"{HEX_COLOR_PATTERN}|^$")
    #: False retires the level (the route first refuses while students are on it).
    is_active: bool | None = None
    updated_by: str


class CreateLevel:
    def __init__(self, *, programs: ProgramRepository, levels: LevelRepository) -> None:
        self._programs = programs
        self._levels = levels

    async def execute(self, cmd: CreateLevelCommand) -> Level:
        program = await self._programs.get(cmd.program_id)
        if program is None:
            raise ProgramNotFound("program not found", program_id=cmd.program_id)
        now = datetime.now(UTC)
        level = Level(
            level_id=str(new_ulid()),
            program_id=cmd.program_id,
            academy_id="",  # injected by repo
            # Numbered by the server past every row, retired ones included.
            sequence=await self._levels.next_sequence(cmd.program_id),
            name=cmd.name,
            description=cmd.description,
            completion_rule=cmd.completion_rule,
            requires_coach_recommendation=cmd.requires_coach_recommendation,
            requires_admin_approval=cmd.requires_admin_approval,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=cmd.created_by,
        )
        await self._levels.save(level)
        return level


class UpdateLevel:
    def __init__(self, *, levels: LevelRepository) -> None:
        self._levels = levels

    async def execute(self, cmd: UpdateLevelCommand) -> Level:
        existing = await self._levels.get(cmd.level_id)
        if existing is None:
            raise LevelNotFound("level not found", level_id=cmd.level_id)
        updated = existing.model_copy(
            update={
                k: v
                for k, v in {
                    "name": cmd.name,
                    "description": cmd.description,
                    "completion_rule": cmd.completion_rule,
                    "requires_coach_recommendation": cmd.requires_coach_recommendation,
                    "requires_admin_approval": cmd.requires_admin_approval,
                    "is_active": cmd.is_active,
                    "updated_at": datetime.now(UTC),
                }.items()
                if v is not None
            }
            | ({"color": cmd.color.upper() or None} if cmd.color is not None else {})
        )
        await self._levels.update(updated)
        return updated


class ListLevels:
    def __init__(self, *, levels: LevelRepository) -> None:
        self._levels = levels

    async def execute(self, program_id: str) -> list[Level]:
        return await self._levels.list_for_program(program_id)


class ReorderLevels:
    """Renumber a program's active levels in the given order; retired ones follow."""

    def __init__(self, *, levels: LevelRepository) -> None:
        self._levels = levels

    async def execute(self, program_id: str, level_ids: list[str]) -> list[str]:
        everything = await self._levels.list_all_for_program(program_id)
        active = [lvl.level_id for lvl in everything if lvl.is_active]
        if len(set(level_ids)) != len(level_ids) or set(level_ids) != set(active):
            raise InvalidOrder(
                "list every active level of the program exactly once", program_id=program_id
            )
        ordered = level_ids + [lvl.level_id for lvl in everything if not lvl.is_active]
        await self._levels.resequence(ordered)
        return ordered


class DeleteLevelCommand(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    deleted_by: str


class DeleteLevel:
    """Delete a level with its skills and criteria, but only while nothing uses it.

    Exists to undo a mistaken save (an AI skill ladder appends levels). Any
    student progress, certificate, recommendation, coach note or attached
    content on the level or its skills refuses the delete with 409, and so
    does any active level after it: an appended ladder is undone from the top
    down, which keeps the numbering the owner sees contiguous.
    """

    def __init__(self, *, levels: LevelRepository, store: LevelDeletionStore) -> None:
        self._levels = levels
        self._store = store

    async def execute(self, cmd: DeleteLevelCommand) -> dict[str, int]:
        level = await self._levels.get(cmd.level_id)
        if level is None:
            raise LevelNotFound("level not found", level_id=cmd.level_id)
        # Usage of the target itself, never looked up through the (active-only) sibling list.
        in_use = dict((await self._store.usage_by_level([cmd.level_id])).get(cmd.level_id, {}))
        later = _later_levels(level, await self._levels.list_for_program(level.program_id))
        if later:
            in_use["later_levels"] = later
        if in_use:
            listed = ", ".join(f"{what.replace('_', ' ')}: {n}" for what, n in in_use.items())
            raise LevelInUse(
                f"Level {level.name!r} is in use ({listed}), so it cannot be deleted.",
                level_id=cmd.level_id,
                in_use=in_use,
            )
        deleted = await self._store.delete_level(cmd.level_id)
        await self._store.record_deleted(level=level, deleted=deleted, actor_id=cmd.deleted_by)
        return deleted


class GetLevelUsage:
    """Per level of a program: what still uses it (empty means it can be deleted)."""

    def __init__(self, *, levels: LevelRepository, store: LevelDeletionStore) -> None:
        self._levels = levels
        self._store = store

    async def execute(self, program_id: str) -> dict[str, dict[str, int]]:
        levels = await self._levels.list_for_program(program_id)
        if not levels:
            return {}
        usage = await self._store.usage_by_level([lv.level_id for lv in levels])
        out: dict[str, dict[str, int]] = {}
        for lv in levels:
            out[lv.level_id] = dict(usage.get(lv.level_id, {}))
            if later := _later_levels(lv, levels):
                out[lv.level_id]["later_levels"] = later
        return out


def _later_levels(level: Level, levels: list[Level]) -> int:
    """Active levels after this one; only the last active level can be deleted."""
    return sum(1 for other in levels if other.sequence > level.sequence)
