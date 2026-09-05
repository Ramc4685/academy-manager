"""Broader SaaS validators and durable outbox retry/lock fields."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0133_broader_validators_and_outbox_retry_lock"

MONEY = ["int", "long", "double", "decimal"]
OPT_ARRAY = ["array", "null"]
OPT_BOOL = ["bool", "null"]
OPT_DATE = ["date", "null"]
OPT_OBJECT = ["object", "null"]
OPT_STRING = ["string", "null"]


def _schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": required,
            "properties": properties,
        }
    }


VALIDATORS: dict[str, dict[str, Any]] = {
    "academies": _schema(
        ["academy_id", "display_name"],
        {
            "academy_id": {"bsonType": "string"},
            "display_name": {"bsonType": "string"},
            "slug": {"bsonType": OPT_STRING},
            "primary_domain": {"bsonType": OPT_STRING},
            "timezone": {"bsonType": OPT_STRING},
            "status": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "academy_settings": _schema(
        ["academy_id"],
        {
            "settings_id": {"bsonType": OPT_STRING},
            "academy_id": {"bsonType": "string"},
            "timezone": {"bsonType": OPT_STRING},
            "fees": {"bsonType": OPT_OBJECT},
            "notifications": {"bsonType": OPT_OBJECT},
            "manual_methods": {"bsonType": OPT_ARRAY},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "platform_roles": _schema(
        ["platform_role_id", "user_id", "role", "status"],
        {
            "platform_role_id": {"bsonType": "string"},
            "user_id": {"bsonType": "string"},
            "role": {"enum": ["platform_admin", "platform_support"]},
            "status": {"enum": ["active", "revoked"]},
            "granted_by": {"bsonType": OPT_STRING},
            "granted_at": {"bsonType": OPT_DATE},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "academy_roles": _schema(
        ["academy_id", "role"],
        {
            "role_id": {"bsonType": OPT_STRING},
            "academy_id": {"bsonType": "string"},
            "role": {"bsonType": "string"},
            "name": {"bsonType": OPT_STRING},
            "permissions": {"bsonType": OPT_ARRAY},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "academy_feature_flags": _schema(
        ["academy_id"],
        {
            "feature_flags_id": {"bsonType": OPT_STRING},
            "academy_id": {"bsonType": "string"},
            "flags": {"bsonType": OPT_OBJECT},
            "features": {"bsonType": OPT_OBJECT},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "sessions": _schema(
        ["academy_id", "session_id"],
        {
            "academy_id": {"bsonType": "string"},
            "session_id": {"bsonType": "string"},
            "coach_id": {"bsonType": OPT_STRING},
            "title": {"bsonType": OPT_STRING},
            "name": {"bsonType": OPT_STRING},
            "location": {"bsonType": OPT_STRING},
            "start_at": {"bsonType": OPT_DATE},
            "end_at": {"bsonType": OPT_DATE},
            "capacity": {"bsonType": ["int", "long", "null"]},
            "max_students": {"bsonType": ["int", "long", "null"]},
            "amount_cents": {"bsonType": [*MONEY, "null"]},
            "status": {"enum": ["scheduled", "cancelled", "completed", "active", "open", None]},
            "days_of_week": {"bsonType": OPT_ARRAY},
            "start_time": {"bsonType": OPT_STRING},
            "end_time": {"bsonType": OPT_STRING},
            "start_date": {"bsonType": OPT_STRING},
            "end_date": {"bsonType": OPT_STRING},
            "timezone": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "session_occurrences": _schema(
        ["occurrence_id", "academy_id", "session_id", "start_at", "end_at"],
        {
            "occurrence_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "session_id": {"bsonType": "string"},
            "template_session_id": {"bsonType": OPT_STRING},
            "start_at": {"bsonType": "date"},
            "end_at": {"bsonType": "date"},
            "status": {"enum": ["scheduled", "cancelled", "completed", None]},
            "scheduled_coach_id": {"bsonType": OPT_STRING},
            "actual_coach_id": {"bsonType": OPT_STRING},
            "substitute_coach_id": {"bsonType": OPT_STRING},
            "coach_assignment_reason": {"bsonType": OPT_STRING},
            "is_billable": {"bsonType": OPT_BOOL},
            "is_payable": {"bsonType": OPT_BOOL},
            "cancellation_reason": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "waitlist": _schema(
        ["waitlist_id", "academy_id", "session_id", "student_id", "parent_id", "joined_at"],
        {
            "waitlist_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "session_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "joined_at": {"bsonType": "date"},
            "status": {"enum": ["waiting", "promoted", "skipped", "removed", None]},
        },
    ),
    "pause_requests": _schema(
        ["pause_request_id", "academy_id", "enrollment_id", "parent_id", "period", "status"],
        {
            "pause_request_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "enrollment_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "student_id": {"bsonType": OPT_STRING},
            "session_id": {"bsonType": OPT_STRING},
            "period": {"bsonType": "string"},
            "pause_kind": {"bsonType": OPT_STRING},
            "resume_on": {"bsonType": OPT_STRING},
            "reason": {"bsonType": OPT_STRING},
            "status": {"enum": ["pending", "approved", "declined"]},
            "created_at": {"bsonType": OPT_DATE},
            "decided_at": {"bsonType": OPT_DATE},
            "decided_by": {"bsonType": OPT_STRING},
        },
    ),
    "enrollment_events": _schema(
        ["event_id", "academy_id", "event_type", "student_id", "effective_at", "occurred_at"],
        {
            "event_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "event_type": {"bsonType": "string"},
            "enrollment_id": {"bsonType": OPT_STRING},
            "waitlist_id": {"bsonType": OPT_STRING},
            "session_id": {"bsonType": OPT_STRING},
            "from_session_id": {"bsonType": OPT_STRING},
            "to_session_id": {"bsonType": OPT_STRING},
            "student_id": {"bsonType": "string"},
            "actor_id": {"bsonType": OPT_STRING},
            "reason": {"bsonType": OPT_STRING},
            "effective_at": {"bsonType": "date"},
            "occurred_at": {"bsonType": "date"},
            "billing_policy": {"bsonType": OPT_STRING},
            # The domain model (`EnrollmentLifecycleEvent.billing_result: str | None`)
            # and every writer emit a short string ("voided=0,autopay=disabled",
            # "future_billing_stopped", "recorded"). OPT_OBJECT here made every
            # admin remove/withdraw/pause 500 in prod once the validator was
            # applied (#657). Migration 0165 re-applies this corrected schema.
            "billing_result": {"bsonType": ["object", "string", "null"]},
            "credit_id": {"bsonType": OPT_STRING},
            "refund_id": {"bsonType": OPT_STRING},
            "metadata": {"bsonType": OPT_OBJECT},
        },
    ),
    "scheduled_enrollment_actions": _schema(
        [
            "action_id",
            "academy_id",
            "action_type",
            "enrollment_id",
            "pause_request_id",
            "run_at",
            "status",
            "created_at",
            "updated_at",
        ],
        {
            "action_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "action_type": {"bsonType": "string"},
            "enrollment_id": {"bsonType": "string"},
            "pause_request_id": {"bsonType": "string"},
            "run_at": {"bsonType": "date"},
            "status": {"bsonType": "string"},
            "attempt_count": {"bsonType": ["int", "long", "null"]},
            "last_attempt_at": {"bsonType": OPT_DATE},
            "last_error": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    ),
    "skill_programs": _schema(
        ["program_id", "academy_id", "sport", "name", "created_at", "updated_at"],
        {
            "program_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "sport": {"bsonType": "string"},
            "name": {"bsonType": "string"},
            "description": {"bsonType": OPT_STRING},
            "is_active": {"bsonType": OPT_BOOL},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "created_by": {"bsonType": OPT_STRING},
        },
    ),
    "skill_levels": _schema(
        ["level_id", "academy_id", "program_id", "sequence", "name", "created_at", "updated_at"],
        {
            "level_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "sequence": {"bsonType": ["int", "long"]},
            "name": {"bsonType": "string"},
            "description": {"bsonType": OPT_STRING},
            "completion_rule": {
                "enum": ["ALL_REQUIRED_SKILLS", "POINTS_BASED", "COACH_APPROVAL_ONLY", None]
            },
            "points_threshold": {"bsonType": ["int", "long", "null"]},
            "requires_coach_recommendation": {"bsonType": OPT_BOOL},
            "requires_admin_approval": {"bsonType": OPT_BOOL},
            "is_active": {"bsonType": OPT_BOOL},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "created_by": {"bsonType": OPT_STRING},
        },
    ),
    "skills": _schema(
        [
            "skill_id",
            "academy_id",
            "program_id",
            "level_id",
            "sequence",
            "name",
            "created_at",
            "updated_at",
        ],
        {
            "skill_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "level_id": {"bsonType": "string"},
            "sequence": {"bsonType": ["int", "long"]},
            "name": {"bsonType": "string"},
            "description": {"bsonType": OPT_STRING},
            "is_required": {"bsonType": OPT_BOOL},
            "scoring_type": {
                "enum": [
                    "ATTEMPT_BASED",
                    "CHECKLIST_BASED",
                    "COACH_APPROVAL",
                    "RALLY_COUNT",
                    "TIME_BASED",
                    "POINTS_BASED",
                    None,
                ]
            },
            "pass_threshold_pct": {"bsonType": ["int", "long", "double", "decimal", "null"]},
            "coach_override_allowed": {"bsonType": OPT_BOOL},
            "is_active": {"bsonType": OPT_BOOL},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "created_by": {"bsonType": OPT_STRING},
        },
    ),
    "skill_criteria": _schema(
        ["criterion_id", "academy_id", "program_id", "level_id", "skill_id", "description"],
        {
            "criterion_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "level_id": {"bsonType": "string"},
            "skill_id": {"bsonType": "string"},
            "description": {"bsonType": "string"},
            "display_order": {"bsonType": ["int", "long"]},
            "created_at": {"bsonType": OPT_DATE},
            "created_by": {"bsonType": OPT_STRING},
        },
    ),
    "external_lesson_refs": _schema(
        ["ref_id", "academy_id", "skill_id", "source", "source_title", "created_at"],
        {
            "ref_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "skill_id": {"bsonType": "string"},
            "source": {"enum": ["BWF_SHUTTLE_TIME", "ACADEMY_CUSTOM", "COACH_CREATED"]},
            "source_title": {"bsonType": "string"},
            "module_name": {"bsonType": OPT_STRING},
            "lesson_range": {"bsonType": OPT_STRING},
            "reference_title": {"bsonType": OPT_STRING},
            "page_hint": {"bsonType": OPT_STRING},
            "internal_note": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
            "created_by": {"bsonType": OPT_STRING},
        },
    ),
    "lesson_cards": _schema(
        [
            "card_id",
            "academy_id",
            "program_id",
            "level_id",
            "skill_ids",
            "slug",
            "lesson_number",
            "title",
            "created_at",
            "updated_at",
        ],
        {
            "card_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "level_id": {"bsonType": "string"},
            "skill_ids": {"bsonType": "array", "items": {"bsonType": "string"}},
            "slug": {"bsonType": "string"},
            "lesson_number": {"bsonType": ["int", "long"]},
            "title": {"bsonType": "string"},
            "goal_summary": {"bsonType": OPT_STRING},
            "teaching_points": {"bsonType": OPT_ARRAY},
            "equipment": {"bsonType": OPT_ARRAY},
            "activity_summary": {"bsonType": OPT_STRING},
            "safety_notes": {"bsonType": OPT_ARRAY},
            "source": {"enum": ["BWF_SHUTTLE_TIME", "ACADEMY_CUSTOM", "COACH_CREATED", None]},
            "module_name": {"bsonType": OPT_STRING},
            "lesson_range": {"bsonType": OPT_STRING},
            "page_hint": {"bsonType": OPT_STRING},
            "resource_links": {"bsonType": OPT_ARRAY},
            "content_hash": {"bsonType": OPT_STRING},
            "display_order": {"bsonType": ["int", "long", "null"]},
            "is_active": {"bsonType": OPT_BOOL},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "created_by": {"bsonType": OPT_STRING},
        },
    ),
    "curriculum_video_refs": _schema(
        ["ref_id", "academy_id", "program_id", "scope", "level_id", "title", "url", "created_at"],
        {
            "ref_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "scope": {"enum": ["LEVEL", "SKILL"]},
            "level_id": {"bsonType": "string"},
            "skill_id": {"bsonType": OPT_STRING},
            "title": {"bsonType": "string"},
            "url": {"bsonType": "string"},
            "display_order": {"bsonType": ["int", "long", "null"]},
            "content_hash": {"bsonType": OPT_STRING},
            "is_active": {"bsonType": OPT_BOOL},
            "created_at": {"bsonType": "date"},
            "created_by": {"bsonType": OPT_STRING},
        },
    ),
    "student_level_progress": _schema(
        ["progress_id", "academy_id", "student_id", "program_id", "level_id", "status"],
        {
            "progress_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "level_id": {"bsonType": "string"},
            "status": {"enum": ["active", "completed", "withdrawn"]},
            "started_at": {"bsonType": OPT_DATE},
            "completed_at": {"bsonType": OPT_DATE},
            "created_at": {"bsonType": OPT_DATE},
        },
    ),
    "student_skill_progress": _schema(
        [
            "skill_progress_id",
            "academy_id",
            "student_id",
            "skill_id",
            "level_id",
            "program_id",
            "status",
            "last_updated_at",
            "last_updated_by",
        ],
        {
            "skill_progress_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "skill_id": {"bsonType": "string"},
            "level_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "status": {
                "enum": [
                    "NOT_STARTED",
                    "INTRODUCED",
                    "LEARNING",
                    "PRACTICING",
                    "TEST_READY",
                    "PASSED",
                    "NEEDS_REVIEW",
                ]
            },
            "introduced_at": {"bsonType": OPT_DATE},
            "last_updated_at": {"bsonType": "date"},
            "last_updated_by": {"bsonType": "string"},
        },
    ),
    "test_attempts": _schema(
        [
            "attempt_id",
            "academy_id",
            "student_id",
            "skill_id",
            "level_id",
            "program_id",
            "coach_id",
            "scoring_type",
            "attempts_count",
            "success_count",
            "score",
            "passed",
            "tested_at",
        ],
        {
            "attempt_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "skill_id": {"bsonType": "string"},
            "level_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "session_id": {"bsonType": OPT_STRING},
            "occurrence_id": {"bsonType": OPT_STRING},
            "coach_id": {"bsonType": "string"},
            "scoring_type": {"bsonType": "string"},
            "attempts_count": {"bsonType": ["int", "long"]},
            "success_count": {"bsonType": ["int", "long"]},
            "score": {"bsonType": ["int", "long", "double", "decimal"]},
            "passed": {"bsonType": "bool"},
            "coach_override": {"bsonType": OPT_BOOL},
            "override_reason": {"bsonType": OPT_STRING},
            "notes": {"bsonType": OPT_STRING},
            "tested_at": {"bsonType": "date"},
        },
    ),
    "level_up_recommendations": _schema(
        [
            "rec_id",
            "academy_id",
            "student_id",
            "from_level_id",
            "to_level_id",
            "program_id",
            "status",
            "recommended_by",
            "recommended_at",
        ],
        {
            "rec_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "from_level_id": {"bsonType": "string"},
            "to_level_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "status": {
                "enum": [
                    "NOT_READY",
                    "READY",
                    "RECOMMENDED",
                    "APPROVED",
                    "REJECTED",
                    "COMPLETED",
                ]
            },
            "recommended_by": {"bsonType": "string"},
            "recommended_at": {"bsonType": "date"},
            "reviewed_by": {"bsonType": OPT_STRING},
            "reviewed_at": {"bsonType": OPT_DATE},
            "rejection_reason": {"bsonType": OPT_STRING},
        },
    ),
    "skill_certificates": _schema(
        [
            "cert_id",
            "academy_id",
            "student_id",
            "program_id",
            "level_id",
            "cert_number",
            "student_name",
            "level_name",
            "program_name",
            "completed_at",
            "issued_by",
            "issued_at",
        ],
        {
            "cert_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "level_id": {"bsonType": "string"},
            "cert_number": {"bsonType": "string"},
            "student_name": {"bsonType": "string"},
            "level_name": {"bsonType": "string"},
            "program_name": {"bsonType": "string"},
            "completed_at": {"bsonType": "date"},
            "issued_by": {"bsonType": "string"},
            "issued_at": {"bsonType": "date"},
        },
    ),
    "coach_skill_notes": _schema(
        ["note_id", "academy_id", "student_id", "skill_id", "coach_id", "created_at"],
        {
            "note_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "skill_id": {"bsonType": "string"},
            "coach_id": {"bsonType": "string"},
            "session_id": {"bsonType": OPT_STRING},
            "body": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
        },
    ),
    "outbox_events": _schema(
        [
            "event_id",
            "name",
            "schema_version",
            "aggregate_id",
            "academy_id",
            "payload",
            "status",
            "attempt_count",
            "created_at",
        ],
        {
            "event_id": {"bsonType": "string"},
            "name": {"bsonType": "string"},
            "schema_version": {"bsonType": ["int", "long"]},
            "aggregate_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "occurred_at": {"bsonType": OPT_DATE},
            "payload": {"bsonType": ["object", "array"]},
            "processed": {"bsonType": ["bool", "null"]},
            "processed_at": {"bsonType": OPT_DATE},
            "status": {"enum": ["pending", "processing", "retry", "processed", "dead_lettered"]},
            "attempt_count": {"bsonType": ["int", "long"]},
            "next_retry_at": {"bsonType": OPT_DATE},
            "locked_until": {"bsonType": OPT_DATE},
            "lock_owner": {"bsonType": OPT_STRING},
            "last_error": {"bsonType": OPT_STRING},
            "replayed_from": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
}


async def _apply_validator(
    db: AsyncIOMotorDatabase, collection_name: str, validator: dict[str, Any]
) -> None:
    try:
        await db.command(
            {
                "collMod": collection_name,
                "validator": validator,
                "validationLevel": "moderate",
                "validationAction": "error",
            }
        )
    except NotImplementedError:
        return
    except OperationFailure as exc:
        if exc.code != 26:
            raise
        try:
            await db.create_collection(
                collection_name,
                validator=validator,
                validationLevel="moderate",
                validationAction="error",
            )
        except CollectionInvalid:
            await db.command(
                {
                    "collMod": collection_name,
                    "validator": validator,
                    "validationLevel": "moderate",
                    "validationAction": "error",
                }
            )


async def _backfill_outbox_retry_fields(db: AsyncIOMotorDatabase) -> None:
    now = datetime.now(UTC)
    await db["outbox_events"].update_many(
        {"status": {"$exists": False}, "processed": True},
        {
            "$set": {
                "status": "processed",
                "attempt_count": 0,
                "locked_until": None,
                "lock_owner": None,
                "updated_at": now,
            }
        },
    )
    await db["outbox_events"].update_many(
        {"status": {"$exists": False}, "processed": {"$ne": True}},
        {
            "$set": {
                "status": "pending",
                "attempt_count": 0,
                "next_retry_at": now,
                "locked_until": None,
                "lock_owner": None,
                "updated_at": now,
            }
        },
    )
    await db["outbox_events"].update_many(
        {"attempt_count": {"$exists": False}},
        {"$set": {"attempt_count": 0, "updated_at": now}},
    )


async def _create_outbox_indexes(db: AsyncIOMotorDatabase) -> None:
    outbox = db["outbox_events"]
    await outbox.create_index(
        [("status", 1), ("next_retry_at", 1), ("locked_until", 1), ("created_at", 1)],
        name="outbox_worker_claim_queue",
    )
    await outbox.create_index(
        [("status", 1), ("attempt_count", 1), ("updated_at", 1)],
        name="outbox_status_attempts",
    )
    await outbox.create_index(
        [("locked_until", 1), ("status", 1)],
        name="outbox_stale_locks",
    )


async def up(db: AsyncIOMotorDatabase) -> None:
    await _backfill_outbox_retry_fields(db)
    await _create_outbox_indexes(db)
    for collection_name, validator in VALIDATORS.items():
        await _apply_validator(db, collection_name, validator)
