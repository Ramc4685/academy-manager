"""Unit tests for local-auth audit readiness checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_readiness_module() -> ModuleType:
    script_dir = Path(__file__).resolve().parents[4] / "scripts" / "dev"
    script_path = script_dir / "check_local_auth_audit_readiness.py"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    spec = importlib.util.spec_from_file_location(
        "check_local_auth_audit_readiness_for_test", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_readiness_refuses_non_local_base_url() -> None:
    module = _load_readiness_module()

    with pytest.raises(SystemExit, match="REFUSING"):
        module.assert_local_base_url("https://academy.example.com")


def test_readiness_defaults_to_local_auth_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_AUTH_BASE_URL", "https://academy.example.com")
    monkeypatch.setenv("LOCAL_AUTH_EVIDENCE_DIR", "/tmp/custom-evidence")

    module = _load_readiness_module()

    assert module.DEFAULT_BASE_URL == "https://academy.example.com"
    assert module.DEFAULT_EVIDENCE_DIR == Path("/tmp/custom-evidence")


def test_readiness_blocks_missing_dynamic_route_ids() -> None:
    module = _load_readiness_module()

    items = module.readiness_items_from_state(
        base_url="http://blno.localhost:3000",
        evidence_dir=Path("/tmp/evidence"),
        inventory=SimpleNamespace(values={}, missing=["LOCAL_AUTH_ADMIN_SESSION_ID"]),
        cleanup_counts={"users": 0},
        report=None,
    )

    assert any(item.status == "block" for item in items)
    assert "LOCAL_AUTH_ADMIN_SESSION_ID" in module.render_markdown(items)
    assert "Result: BLOCKED" in module.render_markdown(items)


def test_readiness_blocks_missing_real_auth_environment() -> None:
    module = _load_readiness_module()

    item = module.auth_env_item({})

    assert item.status == "block"
    assert item.name == "auth_env"
    assert "LOCAL_AUTH_E2E" in item.detail
    assert "LOCAL_AUTH_ADMIN_EMAIL" in item.detail


def test_readiness_accepts_complete_real_auth_environment() -> None:
    module = _load_readiness_module()
    env = {
        "LOCAL_AUTH_E2E": "1",
        "LOCAL_AUTH_ADMIN_EMAIL": "admin@example.test",
        "LOCAL_AUTH_ADMIN_PASSWORD": "password",
        "LOCAL_AUTH_COACH_EMAIL": "coach@example.test",
        "LOCAL_AUTH_COACH_PASSWORD": "password",
        "LOCAL_AUTH_PARENT_EMAIL": "parent@example.test",
        "LOCAL_AUTH_PARENT_PASSWORD": "password",
    }

    item = module.auth_env_item(env)

    assert item.status == "ok"
    assert "credentials are present" in item.detail


def test_readiness_warns_about_partial_synthetic_rows_and_report_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_readiness_module()
    for name in ("LOCAL_AUTH_ADMIN", "LOCAL_AUTH_COACH", "LOCAL_AUTH_PARENT"):
        monkeypatch.setenv(f"{name}_EMAIL", f"{name.lower()}@example.test")
        monkeypatch.setenv(f"{name}_PASSWORD", "password")
    monkeypatch.setenv("LOCAL_AUTH_E2E", "1")
    report = {
        "suites": [
            {
                "title": "local-auth.spec.ts",
                "specs": [
                    {
                        "title": "admin payments",
                        "file": "local-auth.spec.ts",
                        "tests": [
                            {
                                "projectName": "local-auth-chromium-mobile",
                                "status": "failed",
                                "annotations": [],
                                "results": [{"status": "failed", "errors": []}],
                            }
                        ],
                    }
                ],
                "suites": [],
            }
        ]
    }

    items = module.readiness_items_from_state(
        base_url="http://blno.localhost:3000",
        evidence_dir=Path("/tmp/evidence"),
        inventory=SimpleNamespace(values={"LOCAL_AUTH_ADMIN_SESSION_ID": "ses"}, missing=[]),
        cleanup_counts={"users": 1, "students": 1},
        report=report,
    )

    assert not any(item.status == "block" for item in items)
    assert any(item.name == "synthetic_scale_rows" and item.status == "warn" for item in items)
    assert any(item.name == "playwright_report" and item.status == "warn" for item in items)
    assert "Result: READY_WITH_WARNINGS" in module.render_markdown(items)


def test_readiness_accepts_complete_expected_synthetic_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_readiness_module()
    for name in ("LOCAL_AUTH_ADMIN", "LOCAL_AUTH_COACH", "LOCAL_AUTH_PARENT"):
        monkeypatch.setenv(f"{name}_EMAIL", f"{name.lower()}@example.test")
        monkeypatch.setenv(f"{name}_PASSWORD", "password")
    monkeypatch.setenv("LOCAL_AUTH_E2E", "1")

    items = module.readiness_items_from_state(
        base_url="http://blno.localhost:3000",
        evidence_dir=Path("/tmp/evidence"),
        inventory=SimpleNamespace(values={"LOCAL_AUTH_ADMIN_SESSION_ID": "ses"}, missing=[]),
        cleanup_counts=module.EXPECTED_SCALE_PLAN.counts,
        report=None,
    )

    scale_item = next(item for item in items if item.name == "synthetic_scale_rows")
    assert scale_item.status == "ok"
    assert "Expected 250-parent synthetic scale rows are present" in scale_item.detail
