"""Session-type-driven billing indexes.

Parent tuition billing by session type: a ``SessionType`` is a priced
category, and a ``StudentBillingEnrollment`` ties a student to one type
(optionally backed by a Stripe subscription). Tenant-scoped collections.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0111_session_type_billing"


async def up(db: AsyncIOMotorDatabase) -> None:
    session_types = db["session_types"]
    await session_types.create_index(
        "session_type_id",
        unique=True,
        sparse=True,
        name="session_types_id_unique",
    )
    await session_types.create_index(
        [("academy_id", 1), ("name", 1)],
        unique=True,
        name="session_types_academy_name_unique",
    )
    await session_types.create_index(
        [("academy_id", 1), ("is_active", 1)],
        name="session_types_academy_active",
    )

    enrollments = db["student_billing_enrollments"]
    await enrollments.create_index(
        "enrollment_id",
        unique=True,
        sparse=True,
        name="student_billing_enrollments_id_unique",
    )
    await enrollments.create_index(
        [("academy_id", 1), ("student_id", 1), ("session_type_id", 1), ("status", 1)],
        name="student_billing_enrollments_student_type_status",
    )
    await enrollments.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="student_billing_enrollments_parent",
    )
    await enrollments.create_index(
        [("academy_id", 1), ("stripe_subscription_id", 1)],
        sparse=True,
        name="student_billing_enrollments_stripe_subscription",
    )
