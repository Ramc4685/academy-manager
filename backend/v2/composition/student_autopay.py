"""Composition for the admin student detail read (issue #674).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Adapts Enrollment's ``EnrollmentAutopayLookup`` port onto the
Billing repository so the student page can show each current enrollment's
autopay state without Enrollment infrastructure reading Billing's collection.
Pure wiring: the billing repository resolves the tenant from
``current_academy_id()`` at request time, so nothing tenant-specific is
captured here.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.enrollment.application.ports import EnrollmentAutopayLookup
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentDetailQuery,
    GetAdminStudent,
)


class BillingAutopayLookupAdapter(EnrollmentAutopayLookup):
    """Implements Enrollment's autopay lookup using Billing's enrollment repo."""

    def __init__(self, billing_enrollments: MongoStudentBillingEnrollmentRepository) -> None:
        self._billing_enrollments = billing_enrollments

    async def autopay_status_by_enrollment(
        self, enrollment_ids: list[str]
    ) -> dict[str, str | None]:
        return await self._billing_enrollments.autopay_status_by_enrollment(enrollment_ids)


def compose_get_admin_student(db: Any, students: AdminStudentDetailQuery) -> GetAdminStudent:
    return GetAdminStudent(
        students,
        autopay=BillingAutopayLookupAdapter(MongoStudentBillingEnrollmentRepository(db)),
    )
