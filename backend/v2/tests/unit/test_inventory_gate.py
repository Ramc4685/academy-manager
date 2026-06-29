"""Unit tests for the aggregate production-scale inventory audit gate."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parents[4] / "scripts" / "dev"
SCRIPT_PATH = SCRIPT_DIR / "audit_inventory_gate.py"


def _load_module() -> ModuleType:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(
        "audit_inventory_gate_for_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _minimal_manifest() -> dict:
    return {
        "title": "fixture",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/",
                "role": "public",
                "source": "frontend/app/page.tsx",
                "workflows": ["Landing"],
                "controls": {"buttons": [], "inputs": [], "modals": []},
                "states": ["default"],
                "risk_edges": ["Broken link"],
                "acceptance": ["Landing works"],
            }
        ],
        "global_surfaces": [],
    }


def _playwright_report(
    *,
    file_name: str = "local-auth-inventory.spec.ts",
    status: str = "passed",
    title: str = "route",
) -> dict:
    return {
        "suites": [
            {
                "title": file_name,
                "specs": [
                    {
                        "title": title,
                        "file": file_name,
                        "tests": [
                            {
                                "projectName": "local-auth",
                                "status": status,
                                "annotations": [],
                                "results": [{"status": status}],
                            }
                        ],
                    }
                ],
                "suites": [],
            }
        ]
    }


def test_gate_result_prefers_blockers_then_warnings() -> None:
    module = _load_module()

    assert module.result_from_items([module.GateItem("pass", "a", "ok")]) == "CLEAN_PASS"
    assert (
        module.result_from_items(
            [
                module.GateItem("pass", "a", "ok"),
                module.GateItem("warn", "b", "warning"),
            ]
        )
        == "READY_WITH_WARNINGS"
    )
    assert (
        module.result_from_items(
            [
                module.GateItem("warn", "b", "warning"),
                module.GateItem("block", "c", "blocked"),
            ]
        )
        == "BLOCKED"
    )


def test_scale_gate_blocks_when_expected_rows_are_missing() -> None:
    module = _load_module()

    items = module._scale_gate_items({"users": 1})

    assert items == [
        module.GateItem(
            "block",
            "production_scale_rows",
            "Synthetic production-scale rows are not fully applied: users missing 249, academy_memberships missing 250, parent_billing_customers missing 250, subscriptions missing 250, students missing 500",
        )
    ]


def test_playwright_gate_blocks_missing_or_skipped_report() -> None:
    module = _load_module()
    skipped_report = _playwright_report(status="skipped")

    assert module._playwright_gate_items(_minimal_manifest(), None)[0].status == "block"
    skipped_items = module._playwright_gate_items(_minimal_manifest(), skipped_report)
    skipped_item = skipped_items[-1]
    assert skipped_item.status == "block"
    assert "1 real-user tests skipped" in skipped_item.detail


def test_playwright_gate_blocks_partial_inventory_report() -> None:
    module = _load_module()
    report_without_inventory_tests = _playwright_report(file_name="local-auth-qa.spec.ts")

    items = module._playwright_gate_items(
        _minimal_manifest(),
        report_without_inventory_tests,
    )

    completeness_item = items[0]
    assert completeness_item.status == "block"
    assert completeness_item.name == "playwright_report_completeness"
    assert "found 0, expected 1" in completeness_item.detail


def test_playwright_gate_blocks_wrong_inventory_title_even_with_expected_count() -> None:
    module = _load_module()

    items = module._playwright_gate_items(
        _minimal_manifest(),
        _playwright_report(title="stale route renders"),
    )

    completeness_item = items[0]
    assert completeness_item.status == "block"
    assert "missing: public route / renders meaningful content" in completeness_item.detail
    assert "unexpected: stale route renders" in completeness_item.detail


def test_playwright_gate_passes_complete_inventory_report() -> None:
    module = _load_module()

    items = module._playwright_gate_items(
        _minimal_manifest(),
        _playwright_report(
            status="passed",
            title="public route / renders meaningful content",
        ),
    )

    assert items == [
        module.GateItem(
            "pass",
            "playwright_report_completeness",
            "Report includes 1 expected inventory tests.",
        ),
        module.GateItem(
            "pass",
            "real_user_playwright",
            "All 1 real-user tests completed without failure or skip.",
        ),
    ]


def test_gate_report_renders_blocked_state() -> None:
    module = _load_module()
    report = module.build_report(
        [
            module.GateItem("pass", "static_manifest_gaps", "ok"),
            module.GateItem("warn", "potential_control_undercounts", "review"),
            module.GateItem("block", "real_user_playwright", "not run"),
        ]
    )

    markdown = module.render_markdown(report)

    assert report["result"] == "BLOCKED"
    assert report["counts"] == {"pass": 1, "warn": 1, "block": 1}
    assert "BLOCK `real_user_playwright`" in markdown


def test_gate_items_from_state_blocks_current_completion_prerequisites(
    monkeypatch,
) -> None:
    module = _load_module()

    monkeypatch.setattr(module, "_static_gate_items", lambda _manifest: [])
    monkeypatch.setattr(module, "_acceptance_gate_items", lambda _manifest: [])
    monkeypatch.setattr(module, "_control_evidence_gate_items", lambda _manifest: [])

    items = module.gate_items_from_state(
        manifest=_minimal_manifest(),
        base_url="http://blno.localhost:3000",
        evidence_dir=Path("/tmp/evidence"),
        inventory=SimpleNamespace(values={}, missing=["LOCAL_AUTH_ADMIN_SESSION_ID"]),
        cleanup_counts={"users": 1},
        report=None,
    )

    names_by_status = {(item.status, item.name) for item in items}
    assert ("block", "production_scale_rows") in names_by_status
    assert ("block", "dynamic_route_ids") in names_by_status
    assert ("block", "real_user_playwright") in names_by_status
