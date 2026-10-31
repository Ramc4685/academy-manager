"""Parent monthly report card composition.

``_ReportCardProvider`` builds each child's card for a month from state: skills
that reached PASSED in the month (``student_skill_progress.last_updated_at``),
attendance marks in the month, the child's active level, and that level's
first required skill not yet passed (with its practice video, if one exists).
A child with no class mark and no new skill in the month gets no card. It
crosses into student_progress, coaching, curriculum and enrollment here, at
the composition root, so the communications use case stays context-free
(ADR-0005).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from backend.v2.contexts.communications.application.parent_report_card import (
    ChildReportCard,
    FamilyReportCard,
    Focus,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_report_cards import (
    SendParentReportCards,
    month_names,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

_ATTENDED = frozenset({"present", "late"})


class _ReportCardProvider:
    def __init__(
        self,
        *,
        skill_progress: Any,
        level_progress: Any,
        attendance: Any,
        students: Any,
        skills: Any,
        levels: Any,
        video_refs: Any,
        academies: Any,
    ) -> None:
        self._progress = skill_progress
        self._level_progress = level_progress
        self._attendance = attendance
        self._students = students
        self._skills = skills
        self._levels = levels
        self._videos = video_refs
        self._academies = academies

    async def families_for_month(self, start: datetime, end: datetime) -> list[FamilyReportCard]:
        passed = await self._progress.list_passed_between(start, end)
        # shortcut: counts by marked_at, not the class date, so a class marked
        # a day late can land in the next month; join occurrences if it matters.
        marks = [
            m
            for m in await self._attendance.list_marked_between(start, end)
            if m.status != "voided"  # #554: a voided mark counts as unmarked
        ]
        if not passed and not marks:
            return []

        new_skills: dict[str, set[str]] = defaultdict(set)
        for row in passed:
            new_skills[row.student_id].add(row.skill_id)
        marked = Counter(m.student_id for m in marks)
        attended = Counter(m.student_id for m in marks if m.status in _ATTENDED)

        doc = await self._academies.find_by_id(current_academy_id())
        frontend = academy_frontend_url(
            frontend_url=get_settings().frontend_url,
            academy_slug=str((doc or {}).get("slug") or ""),
        )
        month, next_month = month_names(start)
        families: dict[str, list[ChildReportCard]] = defaultdict(list)
        for student in await self._students.by_ids(sorted(set(new_skills) | set(marked))):
            if not student.parent_id:
                continue
            sid = student.student_id
            badge = level_name = None
            focus = None
            active = [
                p for p in await self._level_progress.list_for_student(sid) if p.status == "active"
            ]
            if active:
                current = max(active, key=lambda p: p.started_at)
                level = await self._levels.get(current.level_id)
                if level is not None:
                    badge, level_name = f"L{level.sequence}", level.name
                focus = await self._focus(sid, current.level_id)
            families[student.parent_id].append(
                ChildReportCard(
                    first_name=(student.full_name.split() or ["Your child"])[0],
                    progress_url=f"{frontend}/parent/progress?child={sid}",
                    new_skills=len(new_skills[sid]),
                    classes_attended=attended[sid],
                    classes_marked=marked[sid],
                    level_badge=badge,
                    level_name=level_name,
                    focus=focus,
                )
            )
        return [
            FamilyReportCard(
                parent_id=pid,
                month_name=month,
                next_month_name=next_month,
                children=tuple(sorted(kids, key=lambda c: c.first_name)),
            )
            for pid, kids in sorted(families.items())
        ]

    async def _focus(self, student_id: str, level_id: str) -> Focus | None:
        """The level's first required skill (by sequence) not passed yet."""
        done = {
            p.skill_id
            for p in await self._progress.list_passed_for_student_level(student_id, level_id)
        }
        todo = sorted(
            (
                s
                for s in await self._skills.list_for_level(level_id)
                if s.is_required and s.is_active and s.skill_id not in done
            ),
            key=lambda s: s.sequence,
        )
        if not todo:
            return None
        skill = todo[0]
        videos = [v for v in await self._videos.list_for_skills([skill.skill_id]) if v.is_active]
        return Focus(skill_name=skill.name, video_url=videos[0].url if videos else None)


def compose_send_parent_report_cards(db: Any) -> SendParentReportCards:
    from backend.v2.composition.digests import (
        _AcademyBrandLookup,
        _AcademySlugLookup,
        _build_email_sender,
        compose_unsubscribe_link_builder,
    )
    from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
        MongoAttendanceRepository,
    )
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.communications.infrastructure.mongo_parent_report_card_send_repo import (
        MongoParentReportCardSendRepository,
    )
    from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import (
        MongoLevelRepository,
    )
    from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import (
        MongoSkillRepository,
    )
    from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
        MongoCurriculumVideoRefRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
        MongoStudentRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )
    from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
        MongoStudentLevelProgressRepository,
    )
    from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
        MongoStudentSkillProgressRepository,
    )

    settings = get_settings()
    academies = MongoAcademyRepository(db)
    return SendParentReportCards(
        claims=MongoParentReportCardSendRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings, db),
        provider=_ReportCardProvider(
            skill_progress=MongoStudentSkillProgressRepository(db),
            level_progress=MongoStudentLevelProgressRepository(db),
            attendance=MongoAttendanceRepository(db),
            students=MongoStudentRepository(db),
            skills=MongoSkillRepository(db),
            levels=MongoLevelRepository(db),
            video_refs=MongoCurriculumVideoRefRepository(db),
            academies=academies,
        ),
        unsubscribe_links=compose_unsubscribe_link_builder(settings),
        academy_slugs=_AcademySlugLookup(academies),
        brands=_AcademyBrandLookup(academies),
    )
