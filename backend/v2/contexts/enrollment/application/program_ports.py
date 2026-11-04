"""Ports for programs and per-class public-page fields (Lane B1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from backend.v2.contexts.enrollment.domain.programs import ClassPublicProfile, Program


class ProgramRepository(Protocol):
    """Tenant-scoped ``programs`` store. Every method reads and writes only
    the academy in the request's tenant scope."""

    async def add(self, program: Program) -> Program: ...

    async def get(self, program_id: str) -> Program | None: ...

    async def list_all(self, *, include_archived: bool = False) -> list[Program]: ...

    async def save(self, program: Program) -> Program | None:
        """Overwrite the mutable fields; None when no such program here."""


class ClassPublicProfileRepository(Protocol):
    """The public-page fields on ``sessions`` rows, tenant-scoped.

    ``set_fields`` writes ONLY the given keys (``None`` unsets a key) and
    returns the class's profile after the write, or None when the class is
    not a class of this academy.
    """

    async def get(self, session_id: str) -> ClassPublicProfile | None: ...

    async def list_all(self, *, published_only: bool = False) -> list[ClassPublicProfile]: ...

    async def set_fields(
        self, session_id: str, fields: Mapping[str, Any]
    ) -> ClassPublicProfile | None: ...


@dataclass(frozen=True)
class AssignedWaiver:
    """A live waiver that families in a program must still sign."""

    waiver_template_id: str
    title: str


class ProgramWaiverAssignments(Protocol):
    """Which waivers are assigned to a program (owned by Onboarding).

    Archiving a program does not undo the assignment: the waiver keeps asking
    the program's families to sign, so the admin is told which ones.
    """

    async def waivers_assigned_to(self, program_id: str) -> list[AssignedWaiver]: ...
