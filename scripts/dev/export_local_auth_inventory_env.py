#!/usr/bin/env python3
"""Export seeded local-auth inventory route IDs for Playwright.

This is read-only and local-only. It inspects the BLNO SaaS staging MongoDB and
prints shell exports for dynamic route IDs used by
frontend/e2e/specs/local-auth-inventory.spec.ts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient

_SCRIPTS_DEV_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DEV_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DEV_DIR)

from mongo_guard import assert_local_mongo_url  # noqa: E402

ACADEMY_ID = "blno"
STAGING_DB_NAME = "academy_manager_saas_staging"
DEFAULT_DB_NAME = os.environ.get("SAAS_STAGING_DB_NAME", STAGING_DB_NAME)
DEFAULT_COACH_EMAIL = "gowtham@blno.academy"
DEFAULT_CREDENTIALS_FILE = (
    Path(__file__).resolve().parents[2] / ".local" / "saas-staging-credentials.json"
)


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


@dataclass(frozen=True)
class InventoryEnvResult:
    values: dict[str, str]
    missing: list[str]


def assert_staging_db_name(db_name: str) -> None:
    if db_name != STAGING_DB_NAME:
        raise SystemExit(
            f"REFUSING: Mongo database must be {STAGING_DB_NAME!r}; got {db_name!r}"
        )


def build_inventory_env(
    db: Any, *, academy_id: str = ACADEMY_ID, coach_email: str = DEFAULT_COACH_EMAIL
) -> InventoryEnvResult:
    values: dict[str, str] = {}
    missing: list[str] = []

    def add(env_name: str, value: str | None) -> None:
        if value:
            values[env_name] = value
        else:
            missing.append(env_name)

    admin_session_id = _first_field(
        db,
        "sessions",
        {"academy_id": academy_id, "status": {"$ne": "cancelled"}},
        ("session_id",),
        sort=[("session_id", 1)],
    )
    add("LOCAL_AUTH_ADMIN_SESSION_ID", admin_session_id)
    add(
        "LOCAL_AUTH_ADMIN_STUDENT_ID",
        _first_field(
            db,
            "students",
            {"academy_id": academy_id, "status": "active"},
            ("student_id",),
            sort=[("student_id", 1)],
        ),
    )
    add(
        "LOCAL_AUTH_ADMIN_USER_ID",
        _first_field(
            db,
            "users",
            {"academy_id": academy_id, "roles": {"$in": ["parent"]}},
            ("user_id",),
            sort=[("user_id", 1)],
        ),
    )
    add(
        "LOCAL_AUTH_ADMIN_PAYOUT_ID",
        _first_available_field(
            db,
            (
                ("payout_periods", {"academy_id": academy_id}, ("period_id",)),
                ("payouts", {"academy_id": academy_id}, ("payout_id",)),
            ),
            sort=[("generated_at", -1)],
        ),
    )
    add(
        "LOCAL_AUTH_ADMIN_APPLICATION_ID",
        _first_field(
            db,
            "onboarding_applications",
            {"academy_id": academy_id},
            ("application_id",),
            sort=[("created_at", -1)],
        ),
    )
    add(
        "LOCAL_AUTH_ADMIN_WAIVER_ID",
        _first_field(
            db,
            "waiver_templates",
            {"academy_id": academy_id},
            ("waiver_template_id", "template_id", "waiver_id", "_id"),
            sort=[("created_at", -1)],
        ),
    )
    add(
        "LOCAL_AUTH_ADMIN_WAIVER_SIGNATURE_ID",
        _first_field(
            db,
            "waiver_signatures",
            {"academy_id": academy_id},
            ("waiver_signature_id", "signature_id", "_id"),
            sort=[("signed_at", -1)],
        ),
    )
    program_id = _first_field(
        db,
        "skill_programs",
        {"academy_id": academy_id, "is_active": {"$ne": False}},
        ("program_id",),
        sort=[("created_at", -1)],
    )
    add("LOCAL_AUTH_ADMIN_PROGRAM_ID", program_id)

    coach_id = _first_field(
        db,
        "users",
        {"academy_id": academy_id, "email": coach_email},
        ("user_id",),
    )
    coach_session_id, coach_occurrence, coach_student_id = (
        _first_ready_coach_session(
            db,
            academy_id=academy_id,
            coach_id=coach_id,
            program_id=program_id,
            now=dt.datetime.now(dt.UTC),
        )
        if coach_id and program_id
        else (None, None, None)
    )
    add("LOCAL_AUTH_COACH_SESSION_ID", coach_session_id)
    add(
        "LOCAL_AUTH_COACH_OCCURRENCE_ID",
        str(coach_occurrence.get("occurrence_id"))
        if coach_occurrence and coach_occurrence.get("occurrence_id")
        else None,
    )
    add(
        "LOCAL_AUTH_COACH_SESSION_DATE",
        _date_from_value(coach_occurrence.get("start_at"))
        if coach_occurrence
        else None,
    )
    add("LOCAL_AUTH_COACH_STUDENT_ID", coach_student_id)

    return InventoryEnvResult(
        values=dict(sorted(values.items())), missing=sorted(missing)
    )


def build_credential_env(credentials_file: Path) -> InventoryEnvResult:
    values: dict[str, str] = {}
    missing: list[str] = []
    if not credentials_file.exists():
        return InventoryEnvResult(values=values, missing=_credential_env_names())

    data = json.loads(credentials_file.read_text())

    admin = _first_owner(data)
    _add_credential(values, missing, "LOCAL_AUTH_ADMIN_EMAIL", admin.get("email"))
    _add_credential(values, missing, "LOCAL_AUTH_ADMIN_PASSWORD", admin.get("password"))

    parent = data.get("sample_parent")
    if isinstance(parent, Mapping):
        _add_credential(values, missing, "LOCAL_AUTH_PARENT_EMAIL", parent.get("email"))
        _add_credential(
            values, missing, "LOCAL_AUTH_PARENT_PASSWORD", parent.get("password")
        )
    else:
        _add_credential(values, missing, "LOCAL_AUTH_PARENT_EMAIL", None)
        _add_credential(values, missing, "LOCAL_AUTH_PARENT_PASSWORD", None)

    coach = _first_coach(data)
    _add_credential(values, missing, "LOCAL_AUTH_COACH_EMAIL", coach.get("email"))
    _add_credential(values, missing, "LOCAL_AUTH_COACH_PASSWORD", coach.get("password"))

    return InventoryEnvResult(values=dict(sorted(values.items())), missing=sorted(missing))


def merge_results(*results: InventoryEnvResult) -> InventoryEnvResult:
    values: dict[str, str] = {}
    missing: set[str] = set()
    for result in results:
        values.update(result.values)
        missing.update(result.missing)
    missing.difference_update(values)
    return InventoryEnvResult(values=dict(sorted(values.items())), missing=sorted(missing))


def render_shell_exports(result: InventoryEnvResult) -> str:
    lines = [
        "# Source this after approved local BLNO seed/scale data is present:",
        '#   eval "$(scripts/dev/saas_staging.sh local-auth-env)"',
    ]
    for key, value in result.values.items():
        lines.append(f"export {key}={shlex.quote(value)}")
    for key in result.missing:
        lines.append(f"# missing {key}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", default=DEFAULT_MONGO_URL)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--academy-id", default=ACADEMY_ID)
    parser.add_argument("--coach-email", default=DEFAULT_COACH_EMAIL)
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=DEFAULT_CREDENTIALS_FILE,
        help="Local-only seeded credentials JSON file.",
    )
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    assert_local_mongo_url(args.mongo_url)
    assert_staging_db_name(args.db_name)
    client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5_000)
    try:
        client.admin.command("ping")
        inventory_result = build_inventory_env(
            client[args.db_name],
            academy_id=args.academy_id,
            coach_email=args.coach_email,
        )
    finally:
        client.close()
    result = merge_results(inventory_result, build_credential_env(args.credentials_file))

    if args.format == "json":
        print(
            json.dumps({"values": result.values, "missing": result.missing}, indent=2)
        )
    else:
        print(render_shell_exports(result), end="")
    return 0


def _first_available_field(
    db: Any,
    selectors: tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...],
    *,
    sort: list[tuple[str, int]] | None = None,
) -> str | None:
    for collection, query, fields in selectors:
        value = _first_field(db, collection, query, fields, sort=sort)
        if value:
            return value
    return None


def _first_field(
    db: Any,
    collection: str,
    query: dict[str, Any],
    fields: tuple[str, ...],
    *,
    sort: list[tuple[str, int]] | None = None,
) -> str | None:
    row = _first_doc(db, collection, query, sort=sort)
    if not row:
        return None
    for field in fields:
        value = row.get(field)
        if value:
            return str(value)
    return None


def _first_enrolled_student_with_active_level(
    db: Any, *, academy_id: str, session_id: str, program_id: str
) -> str | None:
    rows = db["enrollments"].find(
        {
            "academy_id": academy_id,
            "session_id": session_id,
            "status": {"$in": ["active", "paused"]},
        },
        {"student_id": 1, "_id": 0},
    ).sort("student_id", 1)
    for row in rows:
        student_id = str(row.get("student_id") or "")
        if not student_id:
            continue
        active = _first_doc(
            db,
            "student_level_progress",
            {
                "student_id": student_id,
                "program_id": program_id,
                "status": "active",
            },
        )
        if active is not None:
            return student_id
    return None


def _first_ready_coach_session(
    db: Any,
    *,
    academy_id: str,
    coach_id: str,
    program_id: str,
    now: dt.datetime,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    rows = db["sessions"].find(
        {
            "academy_id": academy_id,
            "coach_id": coach_id,
            "status": {"$ne": "cancelled"},
        },
        {"session_id": 1, "_id": 0},
    ).sort("session_id", 1)
    fallback_session_id: str | None = None
    fallback_occurrence: dict[str, Any] | None = None
    fallback_student_id: str | None = None

    for row in rows:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            continue
        occurrence = _first_future_occurrence(
            db, academy_id=academy_id, session_id=session_id, now=now
        )
        student_id = _first_enrolled_student_with_active_level(
            db,
            academy_id=academy_id,
            session_id=session_id,
            program_id=program_id,
        )
        if occurrence is not None and student_id:
            return session_id, occurrence, student_id
        if fallback_session_id is None:
            fallback_session_id = session_id
            fallback_occurrence = occurrence
            fallback_student_id = student_id

    return fallback_session_id, fallback_occurrence, fallback_student_id


def _first_future_occurrence(
    db: Any, *, academy_id: str, session_id: str, now: dt.datetime
) -> dict[str, Any] | None:
    return _first_doc(
        db,
        "session_occurrences",
        {
            "academy_id": academy_id,
            "session_id": session_id,
            "status": {"$ne": "cancelled"},
            "start_at": {"$gte": now},
        },
        sort=[("start_at", 1)],
    )


def _first_doc(
    db: Any,
    collection: str,
    query: dict[str, Any],
    *,
    sort: list[tuple[str, int]] | None = None,
) -> dict[str, Any] | None:
    return db[collection].find_one(query, sort=sort)


def _first_owner(data: Mapping[str, Any]) -> dict[str, str | None]:
    owners = data.get("owners")
    if isinstance(owners, Mapping) and owners:
        for email, value in owners.items():
            if isinstance(value, Mapping):
                return {
                    "email": _string_or_none(value.get("owner_email")) or str(email),
                    "password": _string_or_none(value.get("owner_password")),
                }
            return {"email": str(email), "password": _string_or_none(value)}
    return {
        "email": _string_or_none(data.get("owner_email")),
        "password": _string_or_none(data.get("owner_password")),
    }


def _first_coach(data: Mapping[str, Any]) -> dict[str, str | None]:
    coaches = data.get("coaches")
    if isinstance(coaches, Mapping) and coaches:
        for email, password in coaches.items():
            return {"email": str(email), "password": _string_or_none(password)}
    return {"email": None, "password": None}


def _add_credential(
    values: dict[str, str], missing: list[str], env_name: str, value: object
) -> None:
    text = _string_or_none(value)
    if text:
        values[env_name] = text
    else:
        missing.append(env_name)


def _credential_env_names() -> list[str]:
    return [
        "LOCAL_AUTH_ADMIN_EMAIL",
        "LOCAL_AUTH_ADMIN_PASSWORD",
        "LOCAL_AUTH_COACH_EMAIL",
        "LOCAL_AUTH_COACH_PASSWORD",
        "LOCAL_AUTH_PARENT_EMAIL",
        "LOCAL_AUTH_PARENT_PASSWORD",
    ]


def _string_or_none(value: object) -> str | None:
    return str(value) if value else None


def _date_from_value(value: Any) -> str | None:
    if not value:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    text = str(value)
    return text[:10] if len(text) >= 10 else None


if __name__ == "__main__":
    raise SystemExit(main())
