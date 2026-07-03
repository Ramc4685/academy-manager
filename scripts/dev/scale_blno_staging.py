#!/usr/bin/env python3
"""Generate local-only production-scale BLNO SaaS staging data.

This script never reads production data. It creates deterministic synthetic
tenant-owned records on top of the local BLNO seed. Dry-run is the default;
pass --apply to write to local Mongo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from pymongo import MongoClient, UpdateOne

_SCRIPTS_DEV_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DEV_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DEV_DIR)

from mongo_guard import assert_local_mongo_url  # noqa: E402

ACADEMY_ID = "blno"
ACADEMY_TZ = "America/Chicago"
STAGING_DB_NAME = "academy_manager_saas_staging"
DEFAULT_DB_NAME = os.environ.get("SAAS_STAGING_DB_NAME", STAGING_DB_NAME)
DEFAULT_MONTHS = ("2026-04", "2026-05", "2026-06")
SESSION_KEYS = ("wed_beginner", "thu_beginner", "thu_intermediate", "wed_advanced")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def default_mongo_url_from_env(env: Mapping[str, str]) -> str:
    for env_name in (
        "SAAS_STAGING_MONGO_URL",
        "MONGO_URL",
        "MONGODB_URL",
        "MONGODB_URI",
    ):
        mongo_url = env.get(env_name)
        if mongo_url:
            return mongo_url
    return "mongodb://127.0.0.1:27017"


DEFAULT_MONGO_URL = default_mongo_url_from_env(os.environ)


def due_date_for_month(month: str) -> dt.datetime:
    if not MONTH_RE.fullmatch(month):
        return dt.datetime(1970, 1, 5, 0, 0, 0, tzinfo=dt.UTC)
    year, month_number = (int(part) for part in month.split("-", 1))
    return dt.datetime(year, month_number, 5, 0, 0, 0, tzinfo=dt.UTC)


def assert_valid_months(months: list[str]) -> None:
    if not months:
        raise SystemExit("REFUSING: months must not be empty")
    invalid = [month for month in months if not MONTH_RE.fullmatch(month)]
    if invalid:
        raise SystemExit(
            "REFUSING: months must use YYYY-MM format with a valid month number: "
            + ", ".join(invalid)
        )


def local_session_time_to_utc(
    session_date: dt.date, time_value: str, timezone_name: str
) -> dt.datetime:
    hour, minute = (int(part) for part in time_value.split(":", 1))
    local_value = dt.datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        hour,
        minute,
        tzinfo=ZoneInfo(timezone_name),
    )
    return local_value.astimezone(dt.UTC)


@dataclass(frozen=True)
class ScalePlan:
    parents: list[dict[str, Any]]
    users: list[dict[str, Any]]
    memberships: list[dict[str, Any]]
    parent_billing_customers: list[dict[str, Any]]
    subscriptions: list[dict[str, Any]]
    students: list[dict[str, Any]]
    enrollments: list[dict[str, Any]]
    invoices: list[dict[str, Any]]
    invoice_lines: list[dict[str, Any]]
    ledger_payments: list[dict[str, Any]]
    payment_allocations: list[dict[str, Any]]
    payout_periods: list[dict[str, Any]]
    payout_period_lines: list[dict[str, Any]]
    onboarding_applications: list[dict[str, Any]]
    waiver_templates: list[dict[str, Any]]
    waiver_signatures: list[dict[str, Any]]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "users": len(self.users),
            "academy_memberships": len(self.memberships),
            "parent_billing_customers": len(self.parent_billing_customers),
            "subscriptions": len(self.subscriptions),
            "students": len(self.students),
            "enrollments": len(self.enrollments),
            "invoices": len(self.invoices),
            "invoice_lines": len(self.invoice_lines),
            "ledger_payments": len(self.ledger_payments),
            "payment_allocations": len(self.payment_allocations),
            "payout_periods": len(self.payout_periods),
            "payout_period_lines": len(self.payout_period_lines),
            "onboarding_applications": len(self.onboarding_applications),
            "waiver_templates": len(self.waiver_templates),
            "waiver_signatures": len(self.waiver_signatures),
        }


def assert_staging_db_name(db_name: str) -> None:
    if db_name != STAGING_DB_NAME:
        raise SystemExit(
            f"REFUSING: Mongo database must be {STAGING_DB_NAME!r}; got {db_name!r}"
        )


def _ts() -> dt.datetime:
    return dt.datetime(2026, 6, 16, 12, 0, 0, tzinfo=dt.UTC)


def _session_id(index: int) -> tuple[str, str]:
    key = SESSION_KEYS[index % len(SESSION_KEYS)]
    return key, f"ses_blno_{key}"


def _invoice_status(parent_num: int, student_num: int, month_index: int) -> str:
    return "paid" if (parent_num + student_num + month_index) % 2 == 0 else "open"


def build_scale_plan(
    *,
    parent_count: int,
    students_per_parent: int,
    months: list[str],
) -> ScalePlan:
    if parent_count < 1:
        raise ValueError("parent_count must be >= 1")
    if students_per_parent < 1:
        raise ValueError("students_per_parent must be >= 1")
    if not months:
        raise ValueError("months must not be empty")

    now = _ts()
    parents: list[dict[str, Any]] = []
    users: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []
    customers: list[dict[str, Any]] = []
    subscriptions: list[dict[str, Any]] = []
    students: list[dict[str, Any]] = []
    enrollments: list[dict[str, Any]] = []
    invoices: list[dict[str, Any]] = []
    invoice_lines: list[dict[str, Any]] = []
    ledger_payments: list[dict[str, Any]] = []
    allocations: list[dict[str, Any]] = []
    payout_periods: list[dict[str, Any]] = []
    payout_period_lines: list[dict[str, Any]] = []
    onboarding_applications: list[dict[str, Any]] = []
    waiver_templates: list[dict[str, Any]] = []
    waiver_signatures: list[dict[str, Any]] = []

    for parent_num in range(1, parent_count + 1):
        parent_id = f"user_scale_parent_{parent_num:04d}"
        parent_email = f"scale.parent.{parent_num:04d}@local.academy.test"
        parent_name = f"Scale Parent {parent_num:04d}"
        stripe_customer_id = f"cus_blno_scale_{parent_num:04d}"
        subscription_id = f"sub_blno_scale_{parent_num:04d}"
        parents.append(
            {
                "user_id": parent_id,
                "email": parent_email,
                "display_name": parent_name,
            }
        )
        users.append(
            {
                "user_id": parent_id,
                "firebase_uid": parent_id,
                "auth_uid": parent_id,
                "auth_provider": "synthetic-local",
                "email": parent_email,
                "normalized_email": parent_email,
                "display_name": parent_name,
                "phone": f"55501{parent_num:04d}"[-10:],
                "global_status": "active",
                "is_active": True,
                "roles": ["parent"],
                "role": "parent",
                "academy_id": ACADEMY_ID,
                "created_at": now,
                "updated_at": now,
            }
        )
        memberships.append(
            {
                "membership_id": f"mem_scale_parent_{parent_num:04d}",
                "academy_id": ACADEMY_ID,
                "user_id": parent_id,
                "roles": ["parent"],
                "status": "active",
                "invited_by": "synthetic-local-scale-seed",
                "invited_at": now,
                "accepted_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )
        customers.append(
            {
                "academy_id": ACADEMY_ID,
                "parent_id": parent_id,
                "stripe_customer_id": stripe_customer_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        subscriptions.append(
            {
                "subscription_id": subscription_id,
                "academy_id": ACADEMY_ID,
                "parent_id": parent_id,
                "stripe_subscription_id": subscription_id,
                "processor_refs": {
                    "stripe_customer_id": stripe_customer_id,
                    "stripe_subscription_id": subscription_id,
                },
                "status": "active",
                "payment_mode": "monthly",
                "created_at": now,
                "updated_at": now,
            }
        )

        for student_num in range(1, students_per_parent + 1):
            student_id = f"std_scale_{parent_num:04d}_{student_num:02d}"
            session_key, session_id = _session_id(parent_num + student_num)
            enrollment_id = f"enr_scale_{parent_num:04d}_{student_num:02d}"
            amount_cents = 6000 + ((parent_num + student_num) % 3) * 500
            students.append(
                {
                    "student_id": student_id,
                    "academy_id": ACADEMY_ID,
                    "parent_id": parent_id,
                    "full_name": f"Scale Student {parent_num:04d}-{student_num:02d}",
                    "date_of_birth": f"{2012 + (student_num % 6)}-06-15",
                    "skill_level": ["beginner", "intermediate", "advanced"][
                        student_num % 3
                    ],
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            enrollments.append(
                {
                    "enrollment_id": enrollment_id,
                    "academy_id": ACADEMY_ID,
                    "session_id": session_id,
                    "student_id": student_id,
                    "status": "active",
                    "billing_type": "standard",
                    "created_at": now,
                    "updated_at": now,
                }
            )

            for month_index, month in enumerate(months):
                invoice_id = f"inv_scale_{parent_num:04d}_{student_num:02d}_{month}"
                line_id = f"line_scale_{parent_num:04d}_{student_num:02d}_{month}"
                status = _invoice_status(parent_num, student_num, month_index)
                invoice = {
                    "invoice_id": invoice_id,
                    "academy_id": ACADEMY_ID,
                    "parent_id": parent_id,
                    "student_id": student_id,
                    "enrollment_id": enrollment_id,
                    "period": month,
                    "status": status,
                    "currency": "usd",
                    "subtotal_cents": amount_cents,
                    "total_cents": amount_cents,
                    "balance_due_cents": 0 if status == "paid" else amount_cents,
                    "created_at": now,
                    "updated_at": now,
                    "due_date": due_date_for_month(month),
                    "source": "synthetic-local-scale-seed",
                }
                invoices.append(invoice)
                invoice_lines.append(
                    {
                        "line_id": line_id,
                        "invoice_id": invoice_id,
                        "academy_id": ACADEMY_ID,
                        "student_id": student_id,
                        "enrollment_id": enrollment_id,
                        "description": f"Synthetic tuition {month}",
                        "amount_cents": amount_cents,
                        "currency": "usd",
                        "line_type": "tuition",
                        "quantity": 1,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                if status == "paid":
                    payment_id = f"lp_scale_{parent_num:04d}_{student_num:02d}_{month}"
                    allocation_id = (
                        f"alloc_scale_{parent_num:04d}_{student_num:02d}_{month}"
                    )
                    ledger_payments.append(
                        {
                            "payment_id": payment_id,
                            "academy_id": ACADEMY_ID,
                            "parent_id": parent_id,
                            "student_id": student_id,
                            "invoice_id": invoice_id,
                            "amount_cents": amount_cents,
                            "final_amount_cents": amount_cents,
                            "unapplied_amount_cents": 0,
                            "currency": "usd",
                            "status": "succeeded",
                            "payment_method": "stripe",
                            "stripe_payment_intent_id": (
                                f"pi_blno_scale_{parent_num:04d}_"
                                f"{student_num:02d}_{month.replace('-', '')}"
                            ),
                            "received_at": now,
                            "paid_at": now,
                            "created_at": now,
                            "updated_at": now,
                            "source": "synthetic-local-scale-seed",
                        }
                    )
                    allocations.append(
                        {
                            "allocation_id": allocation_id,
                            "academy_id": ACADEMY_ID,
                            "payment_id": payment_id,
                            "invoice_id": invoice_id,
                            "amount_cents": amount_cents,
                            "created_at": now,
                            "updated_at": now,
                        }
                    )

    first_parent = parents[0]
    first_student = students[0]
    first_enrollment = enrollments[0]
    first_session_id = first_enrollment["session_id"]
    fixture_amount_cents = 7500
    waiver_template_id = "wt_blno_scale_2026"
    waiver_signature_id = "ws_blno_scale_0001"
    content_hash = "sha256:blno-scale-waiver-2026"

    payout_periods.append(
        {
            "period_id": "pp_blno_scale_2026_06",
            "academy_id": ACADEMY_ID,
            "coach_id": "coach_blno_scale_fixture",
            "period_start": dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt.UTC),
            "period_end": dt.datetime(2026, 7, 1, 0, 0, 0, tzinfo=dt.UTC),
            "status": "draft",
            "currency": "USD",
            "total_minor": fixture_amount_cents,
            "unpaid_occurrence_ids": [],
            "unpaid_occurrences": [],
            "payout_warnings": [],
            "generated_at": now,
            "approved_at": None,
            "paid_at": None,
            "paid_method": None,
            "paid_amount_minor": None,
            "paid_reference": None,
            "source": "synthetic-local-scale-seed",
        }
    )
    payout_period_lines.append(
        {
            "period_id": "pp_blno_scale_2026_06",
            "academy_id": ACADEMY_ID,
            "occurrence_id": "occ_blno_scale_payout_2026_06_01",
            "coach_id": "coach_blno_scale_fixture",
            "basis": "scheduled",
            "minutes": "60",
            "amount_minor": fixture_amount_cents,
            "currency": "USD",
            "rate_id": "rate_blno_scale_fixture",
            "percent_bps": 3000,
            "expected_revenue_minor": 25000,
            "original_amount_minor": None,
            "adjustment_reason": None,
            "source": "synthetic-local-scale-seed",
        }
    )
    onboarding_applications.append(
        {
            "application_id": "app_blno_scale_pending",
            "academy_id": ACADEMY_ID,
            "parent_user_id": first_parent["user_id"],
            "parent_email": first_parent["email"],
            "status": "PENDING_APPROVAL",
            "parent_profile": {
                "first_name": "Scale",
                "last_name": "Parent 0001",
                "email": first_parent["email"],
                "phone": "5550100001",
            },
            "child_profile": {
                "first_name": "Scale",
                "last_name": "Applicant",
                "date_of_birth": "2014-06-15",
                "skill_level": "beginner",
            },
            "selected_session_id": first_session_id,
            "waiver_acceptance": {
                "waiver_version": "2026.1",
                "content_hash": content_hash,
                "accepted_at": now,
                "waiver_template_id": waiver_template_id,
            },
            "stripe_checkout_session_id": "cs_blno_scale_pending",
            "payment_id": "pay_blno_scale_pending",
            "student_id": None,
            "enrollment_id": None,
            "waitlist_id": None,
            "decision_reason": None,
            "decided_by": None,
            "decided_at": None,
            "expires_at": dt.datetime(2026, 6, 23, 12, 0, 0, tzinfo=dt.UTC),
            "created_at": now,
            "updated_at": now,
            "source": "synthetic-local-scale-seed",
        }
    )
    waiver_templates.append(
        {
            "waiver_template_id": waiver_template_id,
            "academy_id": ACADEMY_ID,
            "name": "BLNO Scale Test Waiver",
            "title": "BLNO Scale Test Waiver",
            "version": "2026.1",
            "content_hash": content_hash,
            "body": "Sanitized local waiver text for production-scale QA.",
            "effective_from": dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt.UTC),
            "published_at": dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt.UTC),
            "assigned_to_registration": True,
            "assigned_at": now,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "source": "synthetic-local-scale-seed",
        }
    )
    waiver_signatures.append(
        {
            "waiver_signature_id": waiver_signature_id,
            "academy_id": ACADEMY_ID,
            "waiver_template_id": waiver_template_id,
            "student_id": first_student["student_id"],
            "parent_user_id": first_parent["user_id"],
            "signed_at": now,
            "signer_name": first_parent["display_name"],
            "signer_email": first_parent["email"],
            "content_hash": content_hash,
            "ip_address": "127.0.0.1",
            "user_agent": "academy-manager-local-scale-seed",
            "artifact_id": None,
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
            "source": "synthetic-local-scale-seed",
        }
    )

    return ScalePlan(
        parents=parents,
        users=users,
        memberships=memberships,
        parent_billing_customers=customers,
        subscriptions=subscriptions,
        students=students,
        enrollments=enrollments,
        invoices=invoices,
        invoice_lines=invoice_lines,
        ledger_payments=ledger_payments,
        payment_allocations=allocations,
        payout_periods=payout_periods,
        payout_period_lines=payout_period_lines,
        onboarding_applications=onboarding_applications,
        waiver_templates=waiver_templates,
        waiver_signatures=waiver_signatures,
    )


def _upsert_ops(
    rows: list[dict[str, Any]], key_fields: tuple[str, ...]
) -> list[UpdateOne]:
    ops: list[UpdateOne] = []
    for row in rows:
        key = {field: row[field] for field in key_fields}
        ops.append(UpdateOne(key, {"$set": row}, upsert=True))
    return ops


def apply_scale_plan(db: Any, plan: ScalePlan) -> dict[str, int]:
    collections: list[tuple[str, list[dict[str, Any]], tuple[str, ...]]] = [
        ("users", plan.users, ("user_id",)),
        ("academy_memberships", plan.memberships, ("academy_id", "user_id")),
        (
            "parent_billing_customers",
            plan.parent_billing_customers,
            ("academy_id", "parent_id"),
        ),
        ("subscriptions", plan.subscriptions, ("subscription_id",)),
        ("students", plan.students, ("student_id",)),
        ("enrollments", plan.enrollments, ("enrollment_id",)),
        ("invoices", plan.invoices, ("academy_id", "invoice_id")),
        ("invoice_lines", plan.invoice_lines, ("academy_id", "line_id")),
        ("ledger_payments", plan.ledger_payments, ("academy_id", "payment_id")),
        (
            "payment_allocations",
            plan.payment_allocations,
            ("academy_id", "allocation_id"),
        ),
        ("payout_periods", plan.payout_periods, ("academy_id", "period_id")),
        (
            "payout_period_lines",
            plan.payout_period_lines,
            ("academy_id", "period_id", "occurrence_id"),
        ),
        (
            "onboarding_applications",
            plan.onboarding_applications,
            ("academy_id", "application_id"),
        ),
        (
            "waiver_templates",
            plan.waiver_templates,
            ("academy_id", "waiver_template_id"),
        ),
        (
            "waiver_signatures",
            plan.waiver_signatures,
            ("academy_id", "waiver_signature_id"),
        ),
    ]
    applied: dict[str, int] = {}
    for collection_name, rows, key_fields in collections:
        if not rows:
            applied[collection_name] = 0
            continue
        ops = _upsert_ops(rows, key_fields)
        result = db[collection_name].bulk_write(ops, ordered=False)
        applied[collection_name] = result.upserted_count + result.modified_count
    applied.update(apply_scale_support_fixtures(db, plan))
    return applied


def apply_scale_support_fixtures(db: Any, plan: ScalePlan) -> dict[str, int]:
    enrollment, session = _first_scale_enrollment_with_session(db, plan)
    if enrollment is None or session is None:
        return {"student_level_progress": 0, "session_occurrences": 0}

    program = db["skill_programs"].find_one(
        {"academy_id": ACADEMY_ID, "is_active": {"$ne": False}},
        sort=[("created_at", -1)],
    )
    if program is None:
        return {"student_level_progress": 0, "session_occurrences": 0}
    level = db["skill_levels"].find_one(
        {
            "academy_id": ACADEMY_ID,
            "program_id": program["program_id"],
            "is_active": {"$ne": False},
        },
        sort=[("sequence", 1)],
    )
    if level is None:
        return {"student_level_progress": 0, "session_occurrences": 0}

    now = _ts()
    student_id = str(enrollment["student_id"])
    progress_result = db["student_level_progress"].update_one(
        {
            "academy_id": ACADEMY_ID,
            "student_id": student_id,
            "program_id": program["program_id"],
            "level_id": level["level_id"],
        },
        {
            "$setOnInsert": {
                "progress_id": f"lp_scale_{student_id}",
                "academy_id": ACADEMY_ID,
                "student_id": student_id,
                "program_id": program["program_id"],
                "level_id": level["level_id"],
                "status": "active",
                "started_at": dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt.UTC),
                "completed_at": None,
                "created_at": now,
            },
            "$set": {"updated_at": now},
        },
        upsert=True,
    )

    session_date = _future_session_date(session)
    start_at = local_session_time_to_utc(
        session_date,
        str(session.get("start_time") or "18:00"),
        str(session.get("timezone") or ACADEMY_TZ),
    )
    end_at = local_session_time_to_utc(
        session_date,
        str(session.get("end_time") or "19:00"),
        str(session.get("timezone") or ACADEMY_TZ),
    )
    session_id = str(enrollment["session_id"])
    occurrence_id = f"occ_blno_scale_future_{session_id.removeprefix('ses_blno_')}"
    occurrence_result = db["session_occurrences"].update_one(
        {"academy_id": ACADEMY_ID, "occurrence_id": occurrence_id},
        {
            "$setOnInsert": {
                "occurrence_id": occurrence_id,
                "academy_id": ACADEMY_ID,
                "created_at": now,
            },
            "$set": {
                "session_id": session_id,
                "template_session_id": session_id,
                "start_at": start_at,
                "end_at": end_at,
                "status": "scheduled",
                "scheduled_coach_id": str(session["coach_id"]),
                "actual_coach_id": None,
                "substitute_coach_id": None,
                "is_billable": True,
                "is_payable": True,
                "cancellation_reason": None,
                "updated_at": now,
                "source": "synthetic-local-scale-seed",
            },
        },
        upsert=True,
    )

    return {
        "student_level_progress": int(progress_result.upserted_id is not None)
        + progress_result.modified_count,
        "session_occurrences": int(occurrence_result.upserted_id is not None)
        + occurrence_result.modified_count,
    }


def _first_scale_enrollment_with_session(
    db: Any, plan: ScalePlan
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for enrollment in plan.enrollments:
        session = db["sessions"].find_one(
            {"academy_id": ACADEMY_ID, "session_id": enrollment["session_id"]}
        )
        if session is not None and session.get("coach_id"):
            return enrollment, session
    return None, None


def _future_session_date(session: Mapping[str, Any]) -> dt.date:
    days = {str(day) for day in session.get("days_of_week", [])}
    if "Wed" in days:
        return dt.date(2026, 7, 1)
    if "Thu" in days:
        return dt.date(2026, 7, 2)
    return dt.date(2026, 7, 2)


def synthetic_scale_cleanup_filters() -> list[tuple[str, dict[str, Any]]]:
    return [
        ("users", {"user_id": {"$regex": "^user_scale_parent_"}}),
        (
            "academy_memberships",
            {
                "academy_id": ACADEMY_ID,
                "membership_id": {"$regex": "^mem_scale_parent_"},
            },
        ),
        (
            "parent_billing_customers",
            {"academy_id": ACADEMY_ID, "parent_id": {"$regex": "^user_scale_parent_"}},
        ),
        (
            "subscriptions",
            {
                "academy_id": ACADEMY_ID,
                "subscription_id": {"$regex": "^sub_blno_scale_"},
            },
        ),
        (
            "students",
            {"academy_id": ACADEMY_ID, "student_id": {"$regex": "^std_scale_"}},
        ),
        (
            "student_level_progress",
            {"academy_id": ACADEMY_ID, "progress_id": {"$regex": "^lp_scale_std_scale_"}},
        ),
        (
            "session_occurrences",
            {
                "academy_id": ACADEMY_ID,
                "occurrence_id": {"$regex": "^occ_blno_scale_future_"},
            },
        ),
        (
            "enrollments",
            {"academy_id": ACADEMY_ID, "enrollment_id": {"$regex": "^enr_scale_"}},
        ),
        (
            "invoices",
            {"academy_id": ACADEMY_ID, "invoice_id": {"$regex": "^inv_scale_"}},
        ),
        (
            "invoice_lines",
            {"academy_id": ACADEMY_ID, "line_id": {"$regex": "^line_scale_"}},
        ),
        (
            "ledger_payments",
            {"academy_id": ACADEMY_ID, "payment_id": {"$regex": "^lp_scale_"}},
        ),
        (
            "payment_allocations",
            {"academy_id": ACADEMY_ID, "allocation_id": {"$regex": "^alloc_scale_"}},
        ),
        (
            "payout_periods",
            {"academy_id": ACADEMY_ID, "period_id": "pp_blno_scale_2026_06"},
        ),
        (
            "payout_period_lines",
            {"academy_id": ACADEMY_ID, "period_id": "pp_blno_scale_2026_06"},
        ),
        (
            "onboarding_applications",
            {"academy_id": ACADEMY_ID, "application_id": "app_blno_scale_pending"},
        ),
        (
            "waiver_templates",
            {"academy_id": ACADEMY_ID, "waiver_template_id": "wt_blno_scale_2026"},
        ),
        (
            "waiver_signatures",
            {"academy_id": ACADEMY_ID, "waiver_signature_id": "ws_blno_scale_0001"},
        ),
    ]


def count_synthetic_scale_rows(db: Any) -> dict[str, int]:
    return {
        collection_name: db[collection_name].count_documents(query)
        for collection_name, query in synthetic_scale_cleanup_filters()
    }


def delete_synthetic_scale_rows(db: Any) -> dict[str, int]:
    return {
        collection_name: db[collection_name].delete_many(query).deleted_count
        for collection_name, query in synthetic_scale_cleanup_filters()
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", default=DEFAULT_MONGO_URL)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--parents", type=int, default=250)
    parser.add_argument("--students-per-parent", type=int, default=2)
    parser.add_argument("--months", default=",".join(DEFAULT_MONTHS))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write synthetic rows. Without this flag, only print the plan.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Count synthetic scale rows, or delete them when combined with --apply.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    assert_local_mongo_url(args.mongo_url)
    assert_staging_db_name(args.db_name)
    if args.cleanup:
        client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5_000)
        try:
            client.admin.command("ping")
            db = client[args.db_name]
            counts = count_synthetic_scale_rows(db)
            output: dict[str, Any] = {
                "academy_id": ACADEMY_ID,
                "db_name": args.db_name,
                "apply": args.apply,
                "cleanup": True,
                "matched": counts,
            }
            if args.apply:
                output["deleted"] = delete_synthetic_scale_rows(db)
        finally:
            client.close()
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0

    months = [month.strip() for month in args.months.split(",") if month.strip()]
    assert_valid_months(months)
    plan = build_scale_plan(
        parent_count=args.parents,
        students_per_parent=args.students_per_parent,
        months=months,
    )
    output: dict[str, Any] = {
        "academy_id": ACADEMY_ID,
        "db_name": args.db_name,
        "apply": args.apply,
        "counts": plan.counts,
    }
    if args.apply:
        client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5_000)
        try:
            client.admin.command("ping")
            output["applied"] = apply_scale_plan(client[args.db_name], plan)
        finally:
            client.close()
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
