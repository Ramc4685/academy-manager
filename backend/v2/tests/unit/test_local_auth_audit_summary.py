"""Unit tests for local-auth Playwright audit report summaries."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_summary_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[4] / "scripts" / "dev" / "summarize_local_auth_audit.py"
    )
    spec = importlib.util.spec_from_file_location(
        "summarize_local_auth_audit_for_test", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summary_counts_skipped_and_failed_workflows_with_evidence() -> None:
    module = _load_summary_module()
    report = {
        "stats": {"startTime": "2026-06-28T18:00:00Z", "duration": 123, "flaky": 0},
        "suites": [
            {
                "title": "local-auth-inventory.spec.ts",
                "specs": [
                    {
                        "title": "admin route /admin/payments renders",
                        "file": "local-auth-inventory.spec.ts",
                        "tests": [
                            {
                                "projectName": "local-auth-chromium-mobile",
                                "status": "failed",
                                "annotations": [],
                                "results": [
                                    {
                                        "status": "failed",
                                        "errors": [{"message": "Expected no framework error"}],
                                        "attachments": [
                                            {"name": "screenshot", "path": "artifacts/fail.png"},
                                            {"name": "trace", "path": "artifacts/trace.zip"},
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "title": "dynamic route /admin/sessions/[id]",
                        "file": "local-auth-inventory.spec.ts",
                        "tests": [
                            {
                                "projectName": "local-auth-chromium-mobile",
                                "status": "skipped",
                                "annotations": [{"description": "Set LOCAL_AUTH_ADMIN_SESSION_ID"}],
                                "results": [],
                            }
                        ],
                    },
                ],
                "suites": [],
            }
        ],
    }

    tests = module.collect_tests(report)
    summary = module.render_markdown(report, tests)

    assert "- Total tests: 2" in summary
    assert "- Failed: 1" in summary
    assert "- Skipped: 1" in summary
    assert "BUG-CANDIDATE-001" in summary
    assert "Expected no framework error" in summary
    assert "artifacts/fail.png" in summary
    assert "Set LOCAL_AUTH_ADMIN_SESSION_ID" in summary


def test_summary_handles_report_with_only_skipped_tests() -> None:
    module = _load_summary_module()
    report = {
        "stats": {"startTime": "2026-06-28T18:00:00Z", "duration": 10, "flaky": 0},
        "suites": [
            {
                "title": "local-auth-inventory.spec.ts",
                "specs": [
                    {
                        "title": "public route / renders",
                        "file": "local-auth-inventory.spec.ts",
                        "tests": [
                            {
                                "projectName": "local-auth-chromium-mobile",
                                "status": "skipped",
                                "annotations": [{"description": "Set LOCAL_AUTH_E2E=1"}],
                                "results": [],
                            }
                        ],
                    }
                ],
                "suites": [],
            }
        ],
    }

    summary = module.render_markdown(report, module.collect_tests(report))

    assert "- Failed: 0" in summary
    assert "None recorded in this report." in summary
    assert "Set LOCAL_AUTH_E2E=1" in summary
