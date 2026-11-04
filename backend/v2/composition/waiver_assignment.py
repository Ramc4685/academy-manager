"""Composition for per-student waiver status (Settings overhaul Phase 6).

Wiring only. Attached at ``app.state.admin_student_waivers`` by ``main.py`` and
read by ``interfaces/admin/waiver_routes.py`` (``GET /admin/waivers/students/
{student_id}``); kept out of ``composition/admin.py``, which is at its line
budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.onboarding.application.use_cases.student_waiver_status import (
    GetStudentWaiverStatus,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
    MongoParentWaiverRepository,
)


@dataclass(frozen=True)
class AdminStudentWaivers:
    get_student_waiver_status: GetStudentWaiverStatus


def compose_admin_student_waivers(db: Any) -> AdminStudentWaivers:
    return AdminStudentWaivers(
        get_student_waiver_status=GetStudentWaiverStatus(MongoParentWaiverRepository(db))
    )
