"""Unit tests for the dry-run BLNO scale seed safety validator."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parents[4] / "scripts" / "dev"
VALIDATOR_PATH = SCRIPT_DIR / "validate_scale_seed_safety.py"


def _load_validator_module() -> ModuleType:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(
        "validate_scale_seed_safety_for_test",
        VALIDATOR_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _plan(module: ModuleType):
    return module.scale_blno_staging.build_scale_plan(
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )


def test_valid_scale_plan_passes_safety_checks() -> None:
    module = _load_validator_module()
    plan = _plan(module)

    issues = module.validate_plan(
        plan,
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )
    report = module.build_report(
        plan=plan,
        issues=issues,
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )

    assert issues == []
    assert report["result"] == "pass"
    assert report["checks"]["mongo_touched"] is False
    assert report["counts"] == report["expected_counts"]


def test_validator_flags_wrong_tenant_live_secret_and_live_email() -> None:
    module = _load_validator_module()
    plan = _plan(module)
    plan.students[0]["academy_id"] = "prod-academy"
    plan.users[0]["email"] = "real.parent@gmail.com"
    plan.users[0]["api_key"] = "sk_live_not_allowed"

    issues = module.validate_plan(
        plan,
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )

    messages = {issue.message for issue in issues}
    assert "Tenant-owned row is not scoped to BLNO." in messages
    assert "Email is not in the reserved local synthetic domain." in messages
    assert "Email uses a consumer/live domain." in messages
    assert "Value contains a live-secret or production-service marker." in messages


def test_validator_flags_non_synthetic_stripe_reference() -> None:
    module = _load_validator_module()
    plan = _plan(module)
    plan.subscriptions[0]["stripe_subscription_id"] = "sub_123_not_synthetic"

    issues = module.validate_plan(
        plan,
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )

    assert any(
        issue.message == "Stripe-like reference is not clearly synthetic BLNO scale data."
        for issue in issues
    )


def test_validator_flags_count_mismatch() -> None:
    module = _load_validator_module()
    plan = _plan(module)
    plan.invoices.pop()

    issues = module.validate_plan(
        plan,
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )

    assert any(issue.collection == "invoices" and issue.field == "count" for issue in issues)


def test_validator_flags_malformed_months_and_unsafe_ids() -> None:
    module = _load_validator_module()
    plan = module.scale_blno_staging.build_scale_plan(
        parent_count=1,
        students_per_parent=1,
        months=["2026/06"],
    )
    plan.students[0]["student_id"] = "std_scale_0001_01 bad"

    issues = module.validate_plan(
        plan,
        parent_count=1,
        students_per_parent=1,
        months=["2026/06"],
    )

    assert any(issue.field == "months" for issue in issues)
    assert any(
        issue.message == "Generated identifier contains unsafe characters." for issue in issues
    )


def test_validator_flags_relationship_and_billing_inconsistency() -> None:
    module = _load_validator_module()
    plan = _plan(module)
    plan.students[0]["parent_id"] = "user_scale_parent_missing"
    paid_invoice = next(invoice for invoice in plan.invoices if invoice["status"] == "paid")
    paid_invoice["balance_due_cents"] = paid_invoice["total_cents"]
    plan.payment_allocations[0]["amount_cents"] += 1

    issues = module.validate_plan(
        plan,
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )

    messages = {issue.message for issue in issues}
    assert "Student parent does not exist in generated users." in messages
    assert "Invoice balance does not match generated status." in messages
    assert "Allocation amount does not match payment amount." in messages


def test_validator_flags_broad_cleanup_filters(monkeypatch) -> None:
    module = _load_validator_module()
    plan = _plan(module)

    monkeypatch.setattr(
        module.scale_blno_staging,
        "synthetic_scale_cleanup_filters",
        lambda: [("students", {"academy_id": "blno"}), ("users", {})],
    )

    issues = module.validate_plan(
        plan,
        parent_count=2,
        students_per_parent=2,
        months=["2026-05", "2026-06"],
    )

    messages = {issue.message for issue in issues}
    assert "Cleanup filter must include a synthetic exact or prefix selector." in messages
    assert "Cleanup filter must never be empty." in messages


def test_validator_cli_does_not_touch_mongo(monkeypatch, capsys) -> None:
    module = _load_validator_module()

    def fail_mongo(*_args, **_kwargs):
        raise AssertionError("validator must not construct MongoClient")

    monkeypatch.setattr(module.scale_blno_staging, "MongoClient", fail_mongo)

    assert (
        module.main(
            [
                "--parents",
                "1",
                "--students-per-parent",
                "1",
                "--months",
                "2026-06",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["result"] == "pass"


def test_validator_json_cli_passes_without_mongo(capsys) -> None:
    module = _load_validator_module()

    assert (
        module.main(
            [
                "--parents",
                "1",
                "--students-per-parent",
                "1",
                "--months",
                "2026-06",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)

    assert output["result"] == "pass"
    assert output["checks"]["mongo_touched"] is False
    assert output["counts"]["users"] == 1
