"""Student BFF composition root (UIM12).

Deliberately thin: every read the student BFF exposes reuses an
application-layer use case already composed for the parent BFF
(`ParentComposition` — same `GetChildSchedule` instance, same
`StudentProgressComposition`/`CurriculumComposition`, same
`get_academy_info`). `interfaces/student/` must never import
`interfaces/parent/` directly (import-linter enforces persona isolation);
sharing happens here, at the composition layer, which is allowed to see
both.

Only wired when `settings.enable_student_login` is True (see `main.py`) —
callers should not construct this at boot time when the flag is off.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.parent import ParentComposition
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.interfaces.student.deps import ResolvedStudent, StudentUseCases


def compose_student(
    db: AsyncIOMotorDatabase[Any],
    *,
    parent: ParentComposition,
) -> StudentUseCases:
    students_r = MongoStudentRepository(db)

    async def resolve_student(user_id: str) -> ResolvedStudent | None:
        """Turn the authenticated user's id into their own student record.

        Looks up `Student.student_user_id` (tenant-scoped, so this can only
        ever resolve a student within the request's already-resolved
        academy — see `MongoStudentRepository.get_by_student_user_id`).
        Returns `None` when the user has a `student` membership but no
        (or no longer a) linked roster record; routes turn that into 404.
        """
        student = await students_r.get_by_student_user_id(user_id)
        if student is None:
            return None
        return ResolvedStudent(
            student_id=student.student_id,
            parent_id=student.parent_id,
            academy_id=student.academy_id,
            full_name=student.full_name,
        )

    return StudentUseCases(
        resolve_student=resolve_student,
        # Reused verbatim from the parent composition — same GetChildSchedule
        # instance, same StudentProgressComposition/CurriculumComposition.
        # Do NOT reimplement these for the student BFF; the parent and
        # student portals must always show identical schedule/progress data
        # for the same student (plan risk: a mis-resolved student_id would
        # otherwise silently drift between the two views).
        get_child_schedule=parent.get_child_schedule,
        student_progress=parent.student_progress,
        curriculum=parent.curriculum,
        get_academy_info=parent.get_academy_info,
    )
