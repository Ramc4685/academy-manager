"""Parent evening win e-mail composition.

``_ParentWinsProvider`` reads today's wins from state, not events: skills that
reached PASSED today (``student_skill_progress.last_updated_at``) and
certificates issued today (``skill_certificates.issued_at``). An undo reverts
the row to PRACTICING, so an undone tap simply drops out. It crosses into
student_progress, curriculum and enrollment here, at the composition root, so
the communications use case stays context-free (ADR-0005).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from backend.v2.contexts.communications.application.parent_wins import (
    ChildWins,
    FamilyWins,
    LevelUp,
    SkillWins,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_evening_wins import (
    SendParentEveningWins,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url


class _ParentWinsProvider:
    def __init__(
        self,
        *,
        skill_progress: Any,
        certificates: Any,
        students: Any,
        skills: Any,
        levels: Any,
        academies: Any,
    ) -> None:
        self._progress = skill_progress
        self._certs = certificates
        self._students = students
        self._skills = skills
        self._levels = levels
        self._academies = academies

    async def families_with_wins(self, start: datetime, end: datetime) -> list[FamilyWins]:
        passed = await self._progress.list_passed_between(start, end)
        certs = await self._certs.list_issued_between(start, end)
        if not passed and not certs:
            return []

        students = {
            s.student_id: s
            for s in await self._students.by_ids(
                sorted({p.student_id for p in passed} | {c.student_id for c in certs})
            )
        }
        level_ups: dict[str, dict[str, LevelUp]] = defaultdict(dict)
        for cert in certs:
            level_ups[cert.student_id][cert.level_id] = LevelUp(
                level_name=cert.level_name, program_name=cert.program_name
            )
        # Skills passed today in a level that is not finished today, by student.
        open_levels: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for row in passed:
            if row.level_id not in level_ups[row.student_id]:
                open_levels[row.student_id][row.level_id].append(row.skill_id)

        doc = await self._academies.find_by_id(current_academy_id())
        frontend = academy_frontend_url(
            frontend_url=get_settings().frontend_url,
            academy_slug=str((doc or {}).get("slug") or ""),
        )
        skills_by_level: dict[str, dict[str, str]] = {}
        families: dict[str, list[ChildWins]] = defaultdict(list)
        for student_id, student in students.items():
            if not student.parent_id:
                continue
            skill_wins: list[SkillWins] = []
            for level_id, skill_ids in open_levels[student_id].items():
                if level_id not in skills_by_level:
                    skills_by_level[level_id] = {
                        s.skill_id: s.name for s in await self._skills.list_for_level(level_id)
                    }
                names = skills_by_level[level_id]
                today = tuple(names[sid] for sid in sorted(skill_ids) if sid in names)
                if not today:  # only retired skills: nothing worth telling
                    continue
                level = await self._levels.get(level_id)
                done = await self._progress.list_passed_for_student_level(student_id, level_id)
                skill_wins.append(
                    SkillWins(
                        level_name=level.name if level else "this level",
                        skill_names=today,
                        passed_in_level=len({p.skill_id for p in done} & names.keys()),
                        total_in_level=len(names),
                    )
                )
            ups = tuple(level_ups[student_id].values())
            if not ups and not skill_wins:
                continue
            families[student.parent_id].append(
                ChildWins(
                    first_name=(student.full_name.split() or ["Your child"])[0],
                    progress_url=f"{frontend}/parent/progress?child={student_id}",
                    level_ups=ups,
                    skill_wins=tuple(skill_wins),
                )
            )
        return [
            FamilyWins(parent_id=pid, children=tuple(sorted(kids, key=lambda c: c.first_name)))
            for pid, kids in sorted(families.items())
        ]


def compose_send_parent_evening_wins(db: Any) -> SendParentEveningWins:
    from backend.v2.composition.digests import (
        _AcademyBrandLookup,
        _AcademySlugLookup,
        _build_email_sender,
        compose_unsubscribe_link_builder,
    )
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.communications.infrastructure.mongo_parent_win_send_repo import (
        MongoParentWinSendRepository,
    )
    from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import (
        MongoLevelRepository,
    )
    from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import (
        MongoSkillRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
        MongoStudentRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )
    from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
        MongoSkillCertificateRepository,
    )
    from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
        MongoStudentSkillProgressRepository,
    )

    settings = get_settings()
    academies = MongoAcademyRepository(db)
    return SendParentEveningWins(
        claims=MongoParentWinSendRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings, db),
        provider=_ParentWinsProvider(
            skill_progress=MongoStudentSkillProgressRepository(db),
            certificates=MongoSkillCertificateRepository(db),
            students=MongoStudentRepository(db),
            skills=MongoSkillRepository(db),
            levels=MongoLevelRepository(db),
            academies=academies,
        ),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
        academy_slugs=_AcademySlugLookup(academies),
        brands=_AcademyBrandLookup(academies),
    )
