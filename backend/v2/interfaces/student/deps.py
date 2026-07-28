"""Student BFF dependencies (UIM12).

Entirely gated by `settings.enable_student_login` — `request.app.state`
only carries a `student` attribute when the flag is on (see `main.py`), so
`get_student_use_cases` 404s when it's missing rather than raising an
AttributeError that would leak as a 500.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from backend.v2.composition.pathway import CurriculumComposition, StudentProgressComposition
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona


@dataclass(frozen=True)
class ResolvedStudent:
    """The caller's own student record, resolved from `AuthClaims.user_id`.

    Never accept a `student_id` from the client for `/student/*` routes —
    a student's identity is always the one linked to their own login via
    `Student.student_user_id`, resolved server-side by `resolve_student`.
    """

    student_id: str
    parent_id: str
    academy_id: str
    full_name: str


@dataclass
class StudentUseCases:
    # callable(user_id: str) -> ResolvedStudent | None
    resolve_student: object
    # Reused from ParentComposition — see composition/student.py docstring.
    get_child_schedule: object  # callable
    student_progress: StudentProgressComposition | None
    curriculum: CurriculumComposition | None
    get_academy_info: object  # callable(*, academy_id: str) -> dict


def get_student_use_cases(request: Request) -> StudentUseCases:
    use_cases = getattr(request.app.state, "student", None)
    if use_cases is None:
        # Belt-and-braces. In the real app the flag gates `include_router`
        # itself (main.py), so a flag-off request never reaches here — it
        # 404s at routing. This covers the router being mounted without
        # `app.state.student` composed (tests, or a future caller that
        # mounts routers and composition separately): a missing composition
        # must read as "feature off" (404), never as an AttributeError 500.
        raise HTTPException(status_code=404, detail="Not found")
    return use_cases  # type: ignore[no-any-return]


async def get_resolved_student(
    request: Request,
    claims: AuthClaims = Depends(require_persona("student")),
) -> ResolvedStudent:
    """Resolve the caller's own student record, or 404.

    Composed from `require_persona("student")` (role check) +
    `resolve_student` (id lookup) rather than folded into one dependency,
    so each half is independently testable and the persona 404 vs. the
    "membership exists but link is broken" 404 stay visibly distinct in
    code even though both return the same wire response.
    """
    use_cases = get_student_use_cases(request)
    resolved = await use_cases.resolve_student(claims.user_id)  # type: ignore[operator]
    if resolved is None:
        raise HTTPException(status_code=404, detail="Not found")
    return resolved
