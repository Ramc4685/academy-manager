"""Use case: one certificate plus what the printable certificate shows.

The certificate row stores names only. The level number, the skills the
student mastered and the level that comes next are read from the curriculum,
numbered the same way the parent journey numbers its level strip.
"""

from __future__ import annotations

from dataclasses import dataclass

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
                for c in await self._certs.list_for_student(cmd.student_id)
                if c.cert_id == cmd.cert_id
            ),
            None,
        )
        if cert is None:
            return None
        levels = sorted(
            await self._skill_lookup.list_levels_for_program(cert.program_id),
            key=lambda lvl: getattr(lvl, "sequence", 0),
        )
        index = next(
            (i for i, lvl in enumerate(levels) if getattr(lvl, "level_id", None) == cert.level_id),
            None,
        )
        skills = sorted(
            (
                s
                for s in await self._skill_lookup.list_skills_for_level(cert.level_id)
                if getattr(s, "is_required", True)
            ),
            key=lambda s: getattr(s, "sequence", 0),
        )
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
            level_number=None if index is None else index + 1,
            skills=[str(getattr(s, "name", "")) for s in skills],
            next_level=next_level,
            levels=[
                CertificateLevel(
                    name=str(getattr(lvl, "name", "")),
                    color=getattr(lvl, "display_color", None),
                )
                for lvl in levels
            ],
        )
