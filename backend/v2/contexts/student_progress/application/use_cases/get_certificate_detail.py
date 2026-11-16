"""Use case: one certificate plus what the printable certificate shows.

Certificates issued since 0234 carry a snapshot (level number, colour, the
skills mastered) taken at issue, so renaming a skill later never rewrites one.
Older rows fall back to the live curriculum. The level that comes next and the
ladder colours are always live, numbered the way the parent journey numbers
its level strip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    SkillLookup,
)
from backend.v2.contexts.student_progress.domain.models import SkillCertificate


@dataclass(frozen=True)
class GetCertificateDetailCommand:
    student_id: str
    cert_id: str
    #: Admin only: a revoked certificate still opens, with its revoked status.
    include_revoked: bool = False


class CertificateNextLevel(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    name: str
    number: int


class CertificateLevel(BaseModel):
    model_config = {"frozen": True}
    name: str
    #: The level's colour from the curriculum (owner-chosen or the default).
    color: str | None


class CertificateDetail(BaseModel):
    model_config = {"frozen": True}
    certificate: SkillCertificate
    #: Position on the program's level ladder; None when the level is gone.
    level_number: int | None
    skills: list[str]
    next_level: CertificateNextLevel | None
    #: The program's whole level ladder, in order, for the level colours.
    levels: list[CertificateLevel] = []


async def read_level_ladder(
    skill_lookup: SkillLookup, program_id: str, level_id: str
) -> tuple[list[Any], int | None, list[str]]:
    """The program's levels in order, this level's index, its required skill names."""
    levels = sorted(
        await skill_lookup.list_levels_for_program(program_id),
        key=lambda lvl: getattr(lvl, "sequence", 0),
    )
    index = next(
        (i for i, lvl in enumerate(levels) if getattr(lvl, "level_id", None) == level_id),
        None,
    )
    skills = sorted(
        (
            s
            for s in await skill_lookup.list_skills_for_level(level_id)
            if getattr(s, "is_required", True)
        ),
        key=lambda s: getattr(s, "sequence", 0),
    )
    return levels, index, [str(getattr(s, "name", "")) for s in skills]


class GetCertificateDetail:
    def __init__(self, *, certificates: CertificateRepository, skill_lookup: SkillLookup) -> None:
        self._certs = certificates
        self._skill_lookup = skill_lookup

    async def execute(self, cmd: GetCertificateDetailCommand) -> CertificateDetail | None:
        # Scoped by student (and by tenant inside the repo): a cert id from
        # another child never resolves.
        cert = next(
            (
                c
                for c in await self._certs.list_for_student(
                    cmd.student_id, include_revoked=cmd.include_revoked
                )
                if c.cert_id == cmd.cert_id
            ),
            None,
        )
        if cert is None:
            return None
        levels, index, live_skills = await read_level_ladder(
            self._skill_lookup, cert.program_id, cert.level_id
        )
        snapshot = cert.skill_names is not None
        live_number = None if index is None else index + 1
        next_level = None
        if index is not None and index + 1 < len(levels):
            nxt = levels[index + 1]
            next_level = CertificateNextLevel(
                level_id=str(getattr(nxt, "level_id", "")),
                name=str(getattr(nxt, "name", "")),
                number=index + 2,
            )
        return CertificateDetail(
            certificate=cert,
            level_number=cert.level_number if snapshot else live_number,
            skills=cert.skill_names if cert.skill_names is not None else live_skills,
            next_level=next_level,
            levels=[
                CertificateLevel(
                    name=str(getattr(lvl, "name", "")),
                    color=getattr(lvl, "display_color", None),
                )
                for lvl in levels
            ],
        )
