"""Parent drop-off check-in wiring, attached at ``app.state.dropoff_checkins``.

One set of use cases serves the parent (report), coach and admin/front desk
(confirm) and every read that shows check-in state. Confirm writes through
its own ``MarkAttendance`` instance built from the same repositories the coach
BFF uses, so every attendance rule applies unchanged. Tenant is read per
request (``current_academy_id``), never captured here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.v2.composition.coaching_lookups import (
    EnrollmentExpectedRosterLookup,
    EnrollmentLookupAdapter,
    EnrollmentOccurrenceLookup,
    SelfServiceDropoffPolicyLookup,
    StudentGuardianLookup,
)
from backend.v2.contexts.coaching.application.use_cases.dropoff_checkin import (
    ConfirmDropoff,
    DropoffCheckinReads,
    ReportArrival,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_dropoff_checkin_repo import (
    MongoDropoffCheckinRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_self_service_policy_repo import (
    MongoSelfServicePolicyRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.tenancy import current_academy_id


@dataclass(frozen=True)
class DropoffCheckinComposition:
    report: ReportArrival
    confirm: ConfirmDropoff
    reads: DropoffCheckinReads
    #: user id -> display name, for "Reported by X · Confirmed by Y".
    resolve_user_names: Callable[[Sequence[str]], Awaitable[dict[str, str]]]


def compose_dropoff_checkins(
    db: Any, outbox: Outbox, idempotency_store: IdempotencyStore
) -> DropoffCheckinComposition:
    checkins = MongoDropoffCheckinRepository(db)
    policies = SelfServiceDropoffPolicyLookup(MongoSelfServicePolicyRepository(db))
    occurrences = EnrollmentOccurrenceLookup(MongoSessionOccurrenceRepository(db))
    enrollment_repo = MongoEnrollmentRepository(db)
    enrollments = EnrollmentLookupAdapter(enrollment_repo, MongoOccurrenceRosterRepository(db))
    attendance = MongoAttendanceRepository(db)
    users = MongoUserRepository(db)

    async def resolve_user_names(user_ids: Sequence[str]) -> dict[str, str]:
        unique = sorted({uid for uid in user_ids if uid})
        found = await asyncio.gather(*(users.get_by_id(uid) for uid in unique))
        return {uid: user.display_name for uid, user in zip(unique, found, strict=True) if user}

    return DropoffCheckinComposition(
        report=ReportArrival(
            checkins=checkins,
            policies=policies,
            guardians=StudentGuardianLookup(MongoStudentRepository(db)),
            occurrence_lookup=occurrences,
            enrollment_lookup=enrollments,
            academy_id=current_academy_id,
        ),
        confirm=ConfirmDropoff(
            checkins=checkins,
            policies=policies,
            occurrence_lookup=occurrences,
            attendance_repo=attendance,
            mark_attendance=MarkAttendance(
                attendance_repo=attendance,
                occurrence_lookup=occurrences,
                enrollment_lookup=enrollments,
                outbox=outbox,
                idempotency_store=idempotency_store,
                academy_id=current_academy_id,
            ),
        ),
        reads=DropoffCheckinReads(
            checkins=checkins,
            policies=policies,
            occurrence_lookup=occurrences,
            expected_roster=EnrollmentExpectedRosterLookup(
                enrollment_repo, MongoOccurrenceRosterRepository(db)
            ),
        ),
        resolve_user_names=resolve_user_names,
    )
