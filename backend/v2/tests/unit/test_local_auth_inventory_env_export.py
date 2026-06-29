"""Unit tests for exporting seeded local-auth inventory route IDs."""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_export_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "dev"
        / "export_local_auth_inventory_env.py"
    )
    spec = importlib.util.spec_from_file_location(
        "export_local_auth_inventory_env_for_test", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeCollection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def find_one(self, query: dict[str, object], sort: list[tuple[str, int]] | None = None):
        rows = [row for row in self._rows if _matches(row, query)]
        if sort:
            for field, direction in reversed(sort):
                rows.sort(key=lambda row: str(row.get(field, "")), reverse=direction < 0)
        return rows[0] if rows else None

    def find(self, query: dict[str, object], projection: dict[str, int] | None = None):
        rows = [row for row in self._rows if _matches(row, query)]
        if projection:
            keep = {field for field, enabled in projection.items() if enabled}
            rows = [{field: row[field] for field in keep if field in row} for row in rows]
        return FakeCursor(rows)


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def sort(self, field: str, direction: int):
        return sorted(self._rows, key=lambda row: str(row.get(field, "")), reverse=direction < 0)


class FakeDb:
    def __init__(self, rows_by_collection: dict[str, list[dict[str, object]]]) -> None:
        self._collections = {
            name: FakeCollection(rows) for name, rows in rows_by_collection.items()
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.get(name, FakeCollection([]))


def test_build_inventory_env_exports_all_seeded_dynamic_route_ids() -> None:
    module = _load_export_module()
    db = FakeDb(
        {
            "sessions": [
                {"academy_id": "blno", "session_id": "ses_admin", "coach_id": "other"},
                {"academy_id": "blno", "session_id": "ses_coach", "coach_id": "coach_gowtham"},
            ],
            "users": [
                {
                    "academy_id": "blno",
                    "user_id": "coach_gowtham",
                    "email": "gowtham@blno.academy",
                    "roles": ["coach"],
                },
                {
                    "academy_id": "blno",
                    "user_id": "parent_one",
                    "email": "parent@example.test",
                    "roles": ["parent"],
                },
            ],
            "students": [{"academy_id": "blno", "student_id": "student_admin", "status": "active"}],
            "enrollments": [
                {
                    "academy_id": "blno",
                    "session_id": "ses_coach",
                    "student_id": "student_coach",
                    "status": "active",
                }
            ],
            "student_level_progress": [
                {
                    "student_id": "student_coach",
                    "program_id": "program_1",
                    "status": "active",
                }
            ],
            "session_occurrences": [
                {
                    "academy_id": "blno",
                    "session_id": "ses_coach",
                    "occurrence_id": "occ_1",
                    "start_at": dt.datetime(2099, 6, 25, 23, 0, tzinfo=dt.UTC),
                }
            ],
            "payout_periods": [
                {
                    "academy_id": "blno",
                    "period_id": "pay_period_older",
                    "generated_at": "2026-06-01T00:00:00+00:00",
                },
                {
                    "academy_id": "blno",
                    "period_id": "pay_period_1",
                    "generated_at": "2026-06-16T00:00:00+00:00",
                },
            ],
            "onboarding_applications": [{"academy_id": "blno", "application_id": "app_1"}],
            "waiver_templates": [{"academy_id": "blno", "waiver_template_id": "waiver_1"}],
            "waiver_signatures": [{"academy_id": "blno", "waiver_signature_id": "sig_1"}],
            "skill_programs": [{"academy_id": "blno", "program_id": "program_1"}],
        }
    )

    result = module.build_inventory_env(db)

    assert result.values == {
        "LOCAL_AUTH_ADMIN_APPLICATION_ID": "app_1",
        "LOCAL_AUTH_ADMIN_PAYOUT_ID": "pay_period_1",
        "LOCAL_AUTH_ADMIN_PROGRAM_ID": "program_1",
        "LOCAL_AUTH_ADMIN_SESSION_ID": "ses_admin",
        "LOCAL_AUTH_ADMIN_STUDENT_ID": "student_admin",
        "LOCAL_AUTH_ADMIN_USER_ID": "parent_one",
        "LOCAL_AUTH_ADMIN_WAIVER_ID": "waiver_1",
        "LOCAL_AUTH_ADMIN_WAIVER_SIGNATURE_ID": "sig_1",
        "LOCAL_AUTH_COACH_OCCURRENCE_ID": "occ_1",
        "LOCAL_AUTH_COACH_SESSION_DATE": "2099-06-25",
        "LOCAL_AUTH_COACH_SESSION_ID": "ses_coach",
        "LOCAL_AUTH_COACH_STUDENT_ID": "student_coach",
    }
    assert result.missing == []


def test_build_inventory_env_requires_active_level_for_coach_passport_student() -> None:
    module = _load_export_module()
    db = FakeDb(
        {
            "sessions": [
                {"academy_id": "blno", "session_id": "ses_coach", "coach_id": "coach_gowtham"}
            ],
            "users": [
                {
                    "academy_id": "blno",
                    "user_id": "coach_gowtham",
                    "email": "gowtham@blno.academy",
                    "roles": ["coach"],
                }
            ],
            "students": [{"academy_id": "blno", "student_id": "student_admin", "status": "active"}],
            "enrollments": [
                {
                    "academy_id": "blno",
                    "session_id": "ses_coach",
                    "student_id": "student_aaa_unplaced",
                    "status": "active",
                },
                {
                    "academy_id": "blno",
                    "session_id": "ses_coach",
                    "student_id": "student_zzz_placed",
                    "status": "active",
                },
            ],
            "student_level_progress": [
                {
                    "student_id": "student_zzz_placed",
                    "program_id": "program_1",
                    "status": "active",
                }
            ],
            "session_occurrences": [
                {
                    "academy_id": "blno",
                    "session_id": "ses_coach",
                    "occurrence_id": "occ_1",
                    "start_at": dt.datetime(2099, 6, 25, 23, 0, tzinfo=dt.UTC),
                }
            ],
            "payout_periods": [{"academy_id": "blno", "period_id": "pay_period_1"}],
            "onboarding_applications": [{"academy_id": "blno", "application_id": "app_1"}],
            "waiver_templates": [{"academy_id": "blno", "waiver_template_id": "waiver_1"}],
            "waiver_signatures": [{"academy_id": "blno", "waiver_signature_id": "sig_1"}],
            "skill_programs": [{"academy_id": "blno", "program_id": "program_1"}],
        }
    )

    result = module.build_inventory_env(db)

    assert result.values["LOCAL_AUTH_COACH_STUDENT_ID"] == "student_zzz_placed"


def test_build_inventory_env_selects_coach_session_with_future_occurrence_and_passport() -> None:
    module = _load_export_module()
    db = FakeDb(
        {
            "sessions": [
                {
                    "academy_id": "blno",
                    "session_id": "ses_aaa_missing_passport",
                    "coach_id": "coach_gowtham",
                },
                {
                    "academy_id": "blno",
                    "session_id": "ses_zzz_ready",
                    "coach_id": "coach_gowtham",
                },
            ],
            "users": [
                {
                    "academy_id": "blno",
                    "user_id": "coach_gowtham",
                    "email": "gowtham@blno.academy",
                    "roles": ["coach"],
                },
                {
                    "academy_id": "blno",
                    "user_id": "parent_one",
                    "email": "parent@example.test",
                    "roles": ["parent"],
                },
            ],
            "students": [{"academy_id": "blno", "student_id": "student_admin", "status": "active"}],
            "enrollments": [
                {
                    "academy_id": "blno",
                    "session_id": "ses_aaa_missing_passport",
                    "student_id": "student_unplaced",
                    "status": "active",
                },
                {
                    "academy_id": "blno",
                    "session_id": "ses_zzz_ready",
                    "student_id": "student_ready",
                    "status": "active",
                },
            ],
            "student_level_progress": [
                {
                    "student_id": "student_ready",
                    "program_id": "program_1",
                    "status": "active",
                }
            ],
            "session_occurrences": [
                {
                    "academy_id": "blno",
                    "session_id": "ses_aaa_missing_passport",
                    "occurrence_id": "occ_incomplete",
                    "start_at": dt.datetime(2099, 6, 25, 23, 0, tzinfo=dt.UTC),
                },
                {
                    "academy_id": "blno",
                    "session_id": "ses_zzz_ready",
                    "occurrence_id": "occ_ready",
                    "start_at": dt.datetime(2099, 6, 26, 23, 0, tzinfo=dt.UTC),
                },
            ],
            "payout_periods": [{"academy_id": "blno", "period_id": "pay_period_1"}],
            "onboarding_applications": [{"academy_id": "blno", "application_id": "app_1"}],
            "waiver_templates": [{"academy_id": "blno", "waiver_template_id": "waiver_1"}],
            "waiver_signatures": [{"academy_id": "blno", "waiver_signature_id": "sig_1"}],
            "skill_programs": [{"academy_id": "blno", "program_id": "program_1"}],
        }
    )

    result = module.build_inventory_env(db)

    assert result.values["LOCAL_AUTH_COACH_SESSION_ID"] == "ses_zzz_ready"
    assert result.values["LOCAL_AUTH_COACH_OCCURRENCE_ID"] == "occ_ready"
    assert result.values["LOCAL_AUTH_COACH_STUDENT_ID"] == "student_ready"


def test_render_shell_exports_found_values_and_comments_missing_values() -> None:
    module = _load_export_module()
    result = module.InventoryEnvResult(
        values={"LOCAL_AUTH_ADMIN_SESSION_ID": "ses'quoted"},
        missing=["LOCAL_AUTH_ADMIN_PAYOUT_ID"],
    )

    text = module.render_shell_exports(result)

    assert "export LOCAL_AUTH_ADMIN_SESSION_ID='ses'\"'\"'quoted'" in text
    assert "# missing LOCAL_AUTH_ADMIN_PAYOUT_ID" in text


def test_build_credential_env_reads_structured_blno_credentials(tmp_path: Path) -> None:
    module = _load_export_module()
    credentials_file = tmp_path / "saas-staging-credentials.json"
    credentials_file.write_text(
        """
        {
          "owners": {
            "admin@example.test": {
              "owner_email": "admin@example.test",
              "owner_password": "admin-secret"
            }
          },
          "coaches": {
            "coach@example.test": "coach-secret"
          },
          "sample_parent": {
            "email": "parent@example.test",
            "password": "parent-secret"
          }
        }
        """
    )

    result = module.build_credential_env(credentials_file)

    assert result.values == {
        "LOCAL_AUTH_ADMIN_EMAIL": "admin@example.test",
        "LOCAL_AUTH_ADMIN_PASSWORD": "admin-secret",
        "LOCAL_AUTH_COACH_EMAIL": "coach@example.test",
        "LOCAL_AUTH_COACH_PASSWORD": "coach-secret",
        "LOCAL_AUTH_PARENT_EMAIL": "parent@example.test",
        "LOCAL_AUTH_PARENT_PASSWORD": "parent-secret",
    }
    assert result.missing == []


def test_build_credential_env_does_not_stringify_owner_object_as_password(
    tmp_path: Path,
) -> None:
    module = _load_export_module()
    credentials_file = tmp_path / "saas-staging-credentials.json"
    credentials_file.write_text(
        """
        {
          "owners": {
            "admin@example.test": {
              "owner_email": "admin@example.test",
              "owner_password": "admin-secret"
            }
          }
        }
        """
    )

    result = module.build_credential_env(credentials_file)

    assert result.values["LOCAL_AUTH_ADMIN_PASSWORD"] == "admin-secret"
    assert "{" not in result.values["LOCAL_AUTH_ADMIN_PASSWORD"]


def test_merge_results_removes_missing_names_after_values_are_available() -> None:
    module = _load_export_module()

    result = module.merge_results(
        module.InventoryEnvResult(values={}, missing=["LOCAL_AUTH_ADMIN_EMAIL"]),
        module.InventoryEnvResult(
            values={"LOCAL_AUTH_ADMIN_EMAIL": "admin@example.test"}, missing=[]
        ),
    )

    assert result.values == {"LOCAL_AUTH_ADMIN_EMAIL": "admin@example.test"}
    assert result.missing == []


def test_export_refuses_non_local_mongo_targets() -> None:
    module = _load_export_module()

    with pytest.raises(SystemExit, match="REFUSING"):
        module.assert_local_mongo_url("mongodb+srv://prod.example.invalid/app")


def test_export_refuses_non_staging_db_name() -> None:
    module = _load_export_module()

    with pytest.raises(SystemExit, match="REFUSING"):
        module.assert_staging_db_name("academy_manager_local_prod_clone")


def _matches(row: dict[str, object], query: dict[str, object]) -> bool:
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and not _contains_any(actual, expected["$in"]):
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$gte" in expected and actual < expected["$gte"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _contains_any(actual: object, expected_values: object) -> bool:
    if not isinstance(expected_values, list):
        return False
    if isinstance(actual, list):
        return any(value in actual for value in expected_values)
    return actual in expected_values
