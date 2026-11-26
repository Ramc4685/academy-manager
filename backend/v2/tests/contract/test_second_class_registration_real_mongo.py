"""S48 / D-24 on a real mongod: a second class for an enrolled child.

Approval reuses the child's student record, creates one enrollment for the new
class, and the per-class registration lock lets the first class's live row
stand; a second registration for the same class is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationReview,
    ApproveRegistrationCommand,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import MongoStudentWriter
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.contexts.onboarding.domain.errors import ApplicationNotEditable
from backend.v2.contexts.onboarding.domain.models import Application, ChildProfile, ParentProfile
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.shared.tenancy import tenant_scope

ACAD = "acad-s48"
NOW = datetime.now(UTC).replace(microsecond=0)


def _session(session_id: str, title: str, amount_cents: int) -> dict:
    return {
        "academy_id": ACAD,
        "session_id": session_id,
        "title": title,
        "coach_id": "coach-1",
        "location": "Court 1",
        "capacity": 10,
        "status": "scheduled",
        "start_at": NOW + timedelta(days=3),
        "end_at": NOW + timedelta(days=3, hours=1),
        "amount_cents": amount_cents,
    }


def _application(application_id: str, session_id: str) -> Application:
    return Application(
        application_id=application_id,
        academy_id=ACAD,
        parent_user_id="parent-1",
        parent_email="pat@example.com",
        status="PENDING_APPROVAL",
        parent_profile=ParentProfile(first_name="Pat", last_name="Parent", phone="555-0101"),
        child_profile=ChildProfile(
            first_name="Sam",
            last_name="Student",
            date_of_birth="2016-03-04",
            emergency_contact_name="Pat Parent",
            emergency_contact_phone="555-0101",
        ),
        selected_session_id=session_id,
        expires_at=NOW + timedelta(days=7),
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_second_class_is_one_new_enrollment_on_the_same_student(real_db) -> None:
    db = real_db
    await db.sessions.insert_many(
        [_session("sess-sat", "Saturday Squad", 8000), _session("sess-wed", "Wed Clinic", 0)]
    )
    await db.students.insert_one(
        {
            "academy_id": ACAD,
            "student_id": "stu-sam",
            "full_name": "Sam Student",
            "parent_id": "parent-1",
            "date_of_birth": "2016-03-04",
            "status": "active",
        }
    )
    # Sam's first class came through registration before S48: old lock shape.
    await db.enrollments.insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": "enr-sat",
            "session_id": "sess-sat",
            "student_id": "stu-sam",
            "status": "active",
            "registration_student_lock": "stu-sam",
            "created_at": NOW,
        }
    )
    apps = MongoApplicationRepository(db)
    review = AdminRegistrationReview(
        apps=apps,
        sessions=MongoSessionWriter(db),
        students=MongoStudentWriter(db),
        enrollments=MongoEnrollmentWriter(db),
        waitlist=MongoWaitlistRepository(db),
        student_registrations=MongoStudentRepository(db),
        academy_id=None,
    )

    with tenant_scope(ACAD):
        await apps.save(_application("app-wed", "sess-wed"))
        await review.approve(ApproveRegistrationCommand(application_id="app-wed", actor_id="a"))

        await apps.save(_application("app-sat-again", "sess-sat"))
        with pytest.raises(ApplicationNotEditable, match="already enrolled in this class"):
            await review.approve(
                ApproveRegistrationCommand(application_id="app-sat-again", actor_id="a")
            )

    assert await db.students.count_documents({"academy_id": ACAD}) == 1
    rows = await db.enrollments.find({"academy_id": ACAD}, {"_id": 0}).to_list(None)
    assert sorted((r["session_id"], r["student_id"], r["status"]) for r in rows) == [
        ("sess-sat", "stu-sam", "active"),
        ("sess-wed", "stu-sam", "active"),
    ]
