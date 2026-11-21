"""GetCertificateDetail: the certificate row plus curriculum display fields."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_certificate_detail import (
    GetCertificateDetail,
    GetCertificateDetailCommand,
)
from backend.v2.contexts.student_progress.domain.models import SkillCertificate

NOW = datetime(2026, 10, 30, 18, 0, tzinfo=UTC)


def _cert(cert_id: str, student_id: str, level_id: str) -> SkillCertificate:
    return SkillCertificate(
        cert_id=cert_id,
        academy_id="acad-1",
        student_id=student_id,
        program_id="prog-1",
        level_id=level_id,
        cert_number=f"ACM-{cert_id}",
        student_name="Aarav Test",
        level_name="Grip and Control",
        program_name="Badminton Pathway",
        completed_at=NOW,
        issued_by="system:auto_level_up",
        issued_at=NOW,
    )


class _Certs:
    def __init__(self, certs: list[SkillCertificate]) -> None:
        self._certs = certs

    async def list_for_student(
        self, student_id: str, *, include_revoked: bool = False
    ) -> list[SkillCertificate]:
        return [
            c
            for c in self._certs
            if c.student_id == student_id and (include_revoked or c.status != "revoked")
        ]


class _Lookup:
    levels: ClassVar[list[SimpleNamespace]] = [
        SimpleNamespace(
            level_id="lvl-2", name="Net and Movement", sequence=2, display_color="#FACC15"
        ),
        SimpleNamespace(
            level_id="lvl-1", name="Grip and Control", sequence=1, display_color="#F8FAFC"
        ),
    ]
    skills: ClassVar[dict[str, list[SimpleNamespace]]] = {
        "lvl-1": [
            SimpleNamespace(name="V grip", sequence=2, is_required=True),
            SimpleNamespace(name="Thumb grip", sequence=1, is_required=True),
            SimpleNamespace(name="Bonus trick", sequence=3, is_required=False),
        ],
        "lvl-2": [SimpleNamespace(name="Lunge", sequence=1, is_required=True)],
    }

    async def list_levels_for_program(self, program_id: str) -> list[object]:
        return list(self.levels)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return list(self.skills.get(level_id, []))


def _use_case(*certs: SkillCertificate) -> GetCertificateDetail:
    return GetCertificateDetail(certificates=_Certs(list(certs)), skill_lookup=_Lookup())


@pytest.mark.asyncio
async def test_detail_reads_level_number_required_skills_and_next_level() -> None:
    detail = await _use_case(_cert("c1", "s1", "lvl-1")).execute(
        GetCertificateDetailCommand(student_id="s1", cert_id="c1")
    )

    assert detail is not None
    assert detail.certificate.cert_id == "c1"
    assert detail.level_number == 1
    assert detail.skills == ["Thumb grip", "V grip"]
    assert [(lvl.name, lvl.color) for lvl in detail.levels] == [
        ("Grip and Control", "#F8FAFC"),
        ("Net and Movement", "#FACC15"),
    ]
    assert detail.next_level is not None
    assert (detail.next_level.name, detail.next_level.number) == ("Net and Movement", 2)


@pytest.mark.asyncio
async def test_last_level_has_no_next_level() -> None:
    detail = await _use_case(_cert("c2", "s1", "lvl-2")).execute(
        GetCertificateDetailCommand(student_id="s1", cert_id="c2")
    )

    assert detail is not None
    assert detail.level_number == 2
    assert detail.next_level is None


@pytest.mark.asyncio
async def test_cert_of_another_student_is_not_found() -> None:
    detail = await _use_case(_cert("c1", "other-student", "lvl-1")).execute(
        GetCertificateDetailCommand(student_id="s1", cert_id="c1")
    )

    assert detail is None


@pytest.mark.asyncio
async def test_removed_level_keeps_the_certificate_without_a_number() -> None:
    detail = await _use_case(_cert("c3", "s1", "lvl-gone")).execute(
        GetCertificateDetailCommand(student_id="s1", cert_id="c3")
    )

    assert detail is not None
    assert detail.level_number is None
    assert detail.skills == []
    assert detail.next_level is None


@pytest.mark.asyncio
async def test_a_snapshot_wins_over_the_live_curriculum() -> None:
    """A skill renamed (or a level reordered) after issue leaves the certificate alone."""
    issued = _cert("c4", "s1", "lvl-1").model_copy(
        update={"skill_names": ["Old grip name"], "level_number": 3, "level_color": "#123456"}
    )

    detail = await _use_case(issued).execute(
        GetCertificateDetailCommand(student_id="s1", cert_id="c4")
    )

    assert detail is not None
    assert detail.skills == ["Old grip name"]
    assert detail.level_number == 3
    assert detail.certificate.level_color == "#123456"


@pytest.mark.asyncio
async def test_a_revoked_certificate_opens_for_the_admin_only() -> None:
    revoked = _cert("c5", "s1", "lvl-1").model_copy(update={"status": "revoked"})
    use_case = _use_case(revoked)

    hidden = await use_case.execute(GetCertificateDetailCommand(student_id="s1", cert_id="c5"))
    admin = await use_case.execute(
        GetCertificateDetailCommand(student_id="s1", cert_id="c5", include_revoked=True)
    )

    assert hidden is None
    assert admin is not None and admin.certificate.status == "revoked"
