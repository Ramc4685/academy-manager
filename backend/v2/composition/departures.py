"""Composition for stop-all-classes + the leaving report (issue #698).

Kept out of ``composition/admin.py`` for the same reason as
``composition/enrollment_holds.py`` — that module's wiring-line-count ratchet
(``test_composition_is_wiring``). Attached onto the already-built
``AdminUseCases`` object in ``main.py``, after ``compose_admin`` has wired
``withdraw_enrollment`` (``StopAllClasses`` reuses that instance rather than
building its own — it must be the SAME withdraw path a single-enrollment
Drop uses, per the design contract).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import WithdrawEnrollment
from backend.v2.contexts.enrollment.application.use_cases.leaving_report import GetLeavingReport
from backend.v2.contexts.enrollment.application.use_cases.stop_all_classes import StopAllClasses
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
    MongoEnrollmentEventRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import MongoStudentRepository


@dataclass
class DeparturesComposition:
    stop_all_classes: StopAllClasses
    leaving_report: GetLeavingReport


def compose_departures(
    db: Any, *, withdraw_enrollment: WithdrawEnrollment
) -> DeparturesComposition:
    enrollments = MongoEnrollmentRepository(db)
    events = MongoEnrollmentEventRepository(db)
    sessions = MongoSessionRepository(db)
    students = MongoStudentRepository(db)

    stop_all_classes = StopAllClasses(enrollments=enrollments, withdraw=withdraw_enrollment)
    leaving_report = GetLeavingReport(events=events, sessions=sessions, students=students)

    return DeparturesComposition(
        stop_all_classes=stop_all_classes,
        leaving_report=leaving_report,
    )
