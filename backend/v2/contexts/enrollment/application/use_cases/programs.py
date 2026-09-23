"""Admin write use cases for programs and per-class public fields (Lane B1).

* ``CreateProgram`` / ``UpdateProgram`` / ``ArchiveProgram`` / ``ListPrograms``:
  the tenant-scoped Program entity that groups classes on the public page.
* ``AssignClassToProgram``: sets or clears a class's ``program_id``; the
  program must be a live (not archived) program of the same academy.
* ``SetClassPublicFields``: partial update of a class's public-page fields
  (published, price period, coach display, description, level, age band).
* ``ListClassPublicProfiles``: every class's public fields, for the admin
  settings panel (B5) and the public read (B2, ``published_only=True``).

The tenant is never an input: repositories take it from the request's tenant
scope. Partial updates write only the keys the caller sent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from backend.v2.contexts.enrollment.application.program_ports import (
    ClassPublicProfileRepository,
    ProgramRepository,
)
from backend.v2.contexts.enrollment.domain.errors import (
    InvalidClassPublicFields,
    InvalidProgram,
    ProgramNotFound,
    SessionNotFound,
)
from backend.v2.contexts.enrollment.domain.programs import (
    COACH_DISPLAY_OPTIONS,
    DEFAULT_COACH_DISPLAY,
    DEFAULT_PRICE_PERIOD,
    PRICE_PERIODS,
    AgeBand,
    ClassPublicProfile,
    CoachDisplay,
    PricePeriod,
    Program,
)
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id

__all__ = [
    "CLASS_PUBLIC_FIELDS",
    "COACH_DISPLAY_OPTIONS",
    "DEFAULT_COACH_DISPLAY",
    "DEFAULT_PRICE_PERIOD",
    "PRICE_PERIODS",
    "PROGRAM_MUTABLE_FIELDS",
    "AgeBand",
    "ArchiveProgram",
    "AssignClassToProgram",
    "ClassPublicProfile",
    "CoachDisplay",
    "CreateProgram",
    "CreateProgramCommand",
    "ListClassPublicProfiles",
    "ListPrograms",
    "PricePeriod",
    "Program",
    "SetClassPublicFields",
    "UpdateProgram",
]

#: Keys ``UpdateProgram`` accepts.
PROGRAM_MUTABLE_FIELDS = frozenset(
    {"name", "public_description", "level", "age_band", "sort_order", "archived"}
)
#: Keys ``SetClassPublicFields`` accepts. ``program_id`` is deliberately not
#: here: assignment checks the program exists, so it has its own use case.
CLASS_PUBLIC_FIELDS = frozenset(
    {"published", "price_period", "coach_display", "public_description", "level", "age_band"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _bad_fields(exc: ValidationError) -> list[str]:
    return sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})


def _require_bool(fields: Mapping[str, Any], key: str, error: type[DomainError]) -> None:
    # Lax pydantic turns "no" into False; a switch must be a real boolean.
    if key in fields and not isinstance(fields[key], bool):
        raise error(f"{key} must be true or false.", fields=[key])


@dataclass(frozen=True)
class CreateProgramCommand:
    name: str
    public_description: str | None = None
    level: str | None = None
    #: ``{"min_age": 6, "max_age": 9}`` or an ``AgeBand``; None for no band.
    age_band: Mapping[str, Any] | AgeBand | None = None
    #: None appends the program after the academy's last one.
    sort_order: int | None = None


class CreateProgram:
    def __init__(
        self, programs: ProgramRepository, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._programs = programs
        self._clock = clock

    async def execute(self, command: CreateProgramCommand) -> Program:
        sort_order = command.sort_order
        if sort_order is None:
            existing = await self._programs.list_all(include_archived=True)
            sort_order = max((p.sort_order for p in existing), default=-1) + 1
        now = self._clock()
        try:
            program = Program(
                program_id=new_ulid(),
                academy_id=current_academy_id(),
                name=command.name,
                public_description=command.public_description,
                level=command.level,
                age_band=command.age_band,
                sort_order=sort_order,
                created_at=now,
                updated_at=now,
            )
        except ValidationError as exc:
            raise InvalidProgram("Program is not valid.", fields=_bad_fields(exc)) from exc
        return await self._programs.add(program)


class UpdateProgram:
    def __init__(
        self, programs: ProgramRepository, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._programs = programs
        self._clock = clock

    async def execute(self, program_id: str, changes: Mapping[str, Any]) -> Program:
        unknown = sorted(set(changes) - PROGRAM_MUTABLE_FIELDS)
        if unknown:
            raise InvalidProgram("Unknown program field.", fields=unknown)
        _require_bool(changes, "archived", InvalidProgram)
        current = await self._programs.get(program_id)
        if current is None:
            raise ProgramNotFound("Program not found.", program_id=program_id)
        if "name" in changes and changes["name"] is None:
            raise InvalidProgram("A program needs a name.", fields=["name"])
        if "sort_order" in changes and changes["sort_order"] is None:
            raise InvalidProgram("sort_order cannot be empty.", fields=["sort_order"])
        try:
            updated = Program.model_validate(
                {**current.model_dump(), **dict(changes), "updated_at": self._clock()}
            )
        except ValidationError as exc:
            raise InvalidProgram("Program is not valid.", fields=_bad_fields(exc)) from exc
        saved = await self._programs.save(updated)
        if saved is None:  # deleted between the read and the write
            raise ProgramNotFound("Program not found.", program_id=program_id)
        return saved


class ArchiveProgram:
    """Soft delete: the program leaves the public page and the default admin
    list; classes keep their ``program_id`` and read as ungrouped."""

    def __init__(self, update: UpdateProgram) -> None:
        self._update = update

    async def execute(self, program_id: str) -> Program:
        return await self._update.execute(program_id, {"archived": True})


class ListPrograms:
    def __init__(self, programs: ProgramRepository) -> None:
        self._programs = programs

    async def execute(self, *, include_archived: bool = False) -> list[Program]:
        rows = await self._programs.list_all(include_archived=include_archived)
        return sorted(rows, key=lambda p: (p.sort_order, p.name.casefold(), p.program_id))


class AssignClassToProgram:
    def __init__(self, programs: ProgramRepository, profiles: ClassPublicProfileRepository) -> None:
        self._programs = programs
        self._profiles = profiles

    async def execute(self, session_id: str, program_id: str | None) -> ClassPublicProfile:
        if program_id is not None:
            program = await self._programs.get(program_id)
            if program is None or program.archived:
                raise ProgramNotFound("Program not found.", program_id=program_id)
        profile = await self._profiles.set_fields(session_id, {"program_id": program_id})
        if profile is None:
            raise SessionNotFound("Class not found.", session_id=session_id)
        return profile


class SetClassPublicFields:
    def __init__(self, profiles: ClassPublicProfileRepository) -> None:
        self._profiles = profiles

    async def execute(self, session_id: str, changes: Mapping[str, Any]) -> ClassPublicProfile:
        unknown = sorted(set(changes) - CLASS_PUBLIC_FIELDS)
        if unknown:
            raise InvalidClassPublicFields("Unknown class public field.", fields=unknown)
        _require_bool(changes, "published", InvalidClassPublicFields)
        for key in ("published", "coach_display"):
            if key in changes and changes[key] is None:
                raise InvalidClassPublicFields(f"{key} cannot be empty.", fields=[key])
        current = await self._profiles.get(session_id)
        if current is None:
            raise SessionNotFound("Class not found.", session_id=session_id)
        if not changes:
            return current
        try:
            candidate = ClassPublicProfile.model_validate({**current.model_dump(), **dict(changes)})
        except ValidationError as exc:
            raise InvalidClassPublicFields(
                "Class public fields are not valid.", fields=_bad_fields(exc)
            ) from exc
        patch: dict[str, Any] = {}
        for key in changes:
            value = getattr(candidate, key)
            patch[key] = value.model_dump() if isinstance(value, AgeBand) else value
        profile = await self._profiles.set_fields(session_id, patch)
        if profile is None:
            raise SessionNotFound("Class not found.", session_id=session_id)
        return profile


class ListClassPublicProfiles:
    def __init__(self, profiles: ClassPublicProfileRepository) -> None:
        self._profiles = profiles

    async def execute(self, *, published_only: bool = False) -> list[ClassPublicProfile]:
        return await self._profiles.list_all(published_only=published_only)
