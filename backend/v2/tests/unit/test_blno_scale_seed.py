"""Unit tests for local-only BLNO scale seed helpers."""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_scale_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "dev" / "scale_blno_staging.py"
    spec = importlib.util.spec_from_file_location("scale_blno_staging_for_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scale_plan_counts_are_deterministic() -> None:
    module = _load_scale_module()

    plan = module.build_scale_plan(
        parent_count=2,
        students_per_parent=3,
        months=["2026-04", "2026-05"],
    )

    assert plan.counts == {
        "users": 2,
        "academy_memberships": 2,
        "parent_billing_customers": 2,
        "subscriptions": 2,
        "students": 6,
        "enrollments": 6,
        "invoices": 12,
        "invoice_lines": 12,
        "ledger_payments": 6,
        "payment_allocations": 6,
        "payout_periods": 1,
        "payout_period_lines": 1,
        "onboarding_applications": 1,
        "waiver_templates": 1,
        "waiver_signatures": 1,
    }
    assert plan.parents[0]["email"] == "scale.parent.0001@local.academy.test"
    assert plan.students[-1]["student_id"] == "std_scale_0002_03"


def test_scale_plan_status_mix_keeps_open_and_paid_invoices() -> None:
    module = _load_scale_module()

    plan = module.build_scale_plan(
        parent_count=1,
        students_per_parent=4,
        months=["2026-06"],
    )

    statuses = {invoice["status"] for invoice in plan.invoices}
    assert statuses == {"open", "paid"}
    assert len(plan.ledger_payments) < len(plan.invoices)


def test_scale_plan_ledger_payments_match_current_validator_shape() -> None:
    module = _load_scale_module()

    plan = module.build_scale_plan(
        parent_count=1,
        students_per_parent=1,
        months=["2026-04"],
    )

    payment = plan.ledger_payments[0]
    assert payment["status"] == "succeeded"
    assert payment["unapplied_amount_cents"] == 0
    assert payment["payment_method"] == "stripe"
    assert payment["paid_at"] == payment["created_at"]


def test_scale_plan_invoice_due_dates_are_bson_dates() -> None:
    module = _load_scale_module()

    plan = module.build_scale_plan(
        parent_count=1,
        students_per_parent=1,
        months=["2026-06"],
    )

    due_date = plan.invoices[0]["due_date"]
    assert due_date == dt.datetime(2026, 6, 5, 0, 0, 0, tzinfo=dt.UTC)


def test_scale_cli_refuses_malformed_months_before_apply() -> None:
    module = _load_scale_module()

    with pytest.raises(SystemExit, match="REFUSING: months must use YYYY-MM"):
        module.main(["--months", "2026/06"])


def test_scale_future_session_occurrence_times_are_utc() -> None:
    module = _load_scale_module()

    starts_at = module.local_session_time_to_utc(dt.date(2026, 7, 2), "18:45", module.ACADEMY_TZ)

    assert starts_at == dt.datetime(2026, 7, 2, 23, 45, 0, tzinfo=dt.UTC)


def test_scale_seed_refuses_non_local_mongo_targets() -> None:
    module = _load_scale_module()

    with pytest.raises(SystemExit, match="REFUSING"):
        module.assert_local_mongo_url("mongodb+srv://prod.example.invalid/app")


def test_scale_seed_refuses_non_staging_db_name() -> None:
    module = _load_scale_module()

    with pytest.raises(SystemExit, match="REFUSING"):
        module.assert_staging_db_name("academy_manager_local_prod_clone")


def test_scale_seed_reads_common_mongo_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAAS_STAGING_MONGO_URL", raising=False)
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb+srv://prod.example.invalid/app")

    module = _load_scale_module()

    assert module.DEFAULT_MONGO_URL == "mongodb+srv://prod.example.invalid/app"
    with pytest.raises(SystemExit, match="REFUSING"):
        module.main(["--parents", "1", "--students-per-parent", "1"])


def test_scale_seed_prefers_explicit_saas_staging_mongo_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAAS_STAGING_MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("MONGODB_URL", "mongodb+srv://prod.example.invalid/app")

    module = _load_scale_module()

    assert module.DEFAULT_MONGO_URL == "mongodb://127.0.0.1:27017"


def test_scale_plan_includes_dynamic_route_detail_fixtures() -> None:
    module = _load_scale_module()

    plan = module.build_scale_plan(
        parent_count=1,
        students_per_parent=1,
        months=["2026-06"],
    )

    assert plan.payout_periods[0]["period_id"] == "pp_blno_scale_2026_06"
    assert plan.payout_period_lines[0]["period_id"] == "pp_blno_scale_2026_06"
    assert plan.onboarding_applications[0]["application_id"] == "app_blno_scale_pending"
    assert plan.waiver_templates[0]["waiver_template_id"] == "wt_blno_scale_2026"
    assert plan.waiver_signatures[0]["waiver_signature_id"] == "ws_blno_scale_0001"


def test_scale_plan_detail_fixtures_use_sanitized_local_values() -> None:
    module = _load_scale_module()

    plan = module.build_scale_plan(
        parent_count=1,
        students_per_parent=1,
        months=["2026-06"],
    )

    app = plan.onboarding_applications[0]
    signature = plan.waiver_signatures[0]

    assert app["parent_email"].endswith("@local.academy.test")
    assert app["status"] == "PENDING_APPROVAL"
    assert app["selected_session_id"].startswith("ses_blno_")
    assert signature["signer_email"].endswith("@local.academy.test")
    assert signature["student_id"] == plan.students[0]["student_id"]


def test_synthetic_scale_cleanup_filters_scope_to_generated_rows() -> None:
    module = _load_scale_module()

    filters = dict(module.synthetic_scale_cleanup_filters())

    assert filters["users"] == {"user_id": {"$regex": "^user_scale_parent_"}}
    assert filters["academy_memberships"] == {
        "academy_id": "blno",
        "membership_id": {"$regex": "^mem_scale_parent_"},
    }
    assert filters["invoices"] == {
        "academy_id": "blno",
        "invoice_id": {"$regex": "^inv_scale_"},
    }
    assert filters["student_level_progress"] == {
        "academy_id": "blno",
        "progress_id": {"$regex": "^lp_scale_std_scale_"},
    }
    assert filters["session_occurrences"] == {
        "academy_id": "blno",
        "occurrence_id": {"$regex": "^occ_blno_scale_future_"},
    }
    assert filters["payout_periods"] == {
        "academy_id": "blno",
        "period_id": "pp_blno_scale_2026_06",
    }
    assert filters["onboarding_applications"] == {
        "academy_id": "blno",
        "application_id": "app_blno_scale_pending",
    }
    assert filters["waiver_templates"] == {
        "academy_id": "blno",
        "waiver_template_id": "wt_blno_scale_2026",
    }
    assert filters["waiver_signatures"] == {
        "academy_id": "blno",
        "waiver_signature_id": "ws_blno_scale_0001",
    }
