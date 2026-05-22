"""Add indexes for platform governance request persistence."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0108_platform_governance_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db.tenant_export_requests.create_index(
        "export_request_id",
        name="tenant_export_requests_id_unique",
        unique=True,
    )
    await db.tenant_export_requests.create_index(
        [("academy_id", 1), ("status", 1), ("created_at", -1)],
        name="tenant_export_requests_academy_status_created",
    )

    await db.tenant_deletion_requests.create_index(
        "deletion_request_id",
        name="tenant_deletion_requests_id_unique",
        unique=True,
    )
    await db.tenant_deletion_requests.create_index(
        [("academy_id", 1), ("status", 1), ("created_at", -1)],
        name="tenant_deletion_requests_academy_status_created",
    )

    await db.student_data_deletion_requests.create_index(
        "student_deletion_request_id",
        name="student_data_deletion_requests_id_unique",
        unique=True,
    )
    await db.student_data_deletion_requests.create_index(
        [("academy_id", 1), ("student_id", 1), ("status", 1), ("created_at", -1)],
        name="student_data_deletion_requests_academy_student_status_created",
    )

    await db.support_access_grants.create_index(
        "support_access_grant_id",
        name="support_access_grants_id_unique",
        unique=True,
    )
    await db.support_access_grants.create_index(
        [("academy_id", 1), ("support_user_id", 1), ("status", 1), ("expires_at", 1)],
        name="support_access_grants_academy_user_status_expires",
    )

    await db.support_impersonation_requests.create_index(
        "impersonation_request_id",
        name="support_impersonation_requests_id_unique",
        unique=True,
    )
    await db.support_impersonation_requests.create_index(
        [("academy_id", 1), ("target_user_id", 1), ("status", 1), ("created_at", -1)],
        name="support_impersonation_requests_academy_target_status_created",
    )

    await db.platform_governance_audit_logs.create_index(
        [("academy_id", 1), ("created_at", -1)],
        name="platform_governance_audit_logs_academy_created",
    )
    await db.platform_governance_audit_logs.create_index(
        [("request_id", 1), ("created_at", -1)],
        name="platform_governance_audit_logs_request_created",
    )
