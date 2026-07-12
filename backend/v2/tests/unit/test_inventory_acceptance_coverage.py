"""Unit tests for inventory acceptance coverage reports."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "dev"
    / "audit_inventory_acceptance_coverage.py"
)
REPO_ROOT = Path(__file__).resolve().parents[4]
MANIFEST = REPO_ROOT / "docs" / "qa" / "2026-06-28-production-scale-local-inventory-manifest.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "audit_inventory_acceptance_coverage_for_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_acceptance_report_flags_routes_below_workflow_or_risk_count() -> None:
    module = _load_module()
    manifest = {
        "title": "fixture",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/admin/payments",
                "workflows": ["Review invoices", "Retry webhook", "Reconcile"],
                "controls": {"buttons": ["Retry"], "inputs": [], "modals": []},
                "states": ["loading", "error"],
                "risk_edges": ["Double payment", "Webhook replay"],
                "acceptance": ["Cannot double-pay"],
            }
        ],
        "global_surfaces": [],
    }

    report = module.build_report(manifest)

    assert report["finding_count"] == 1
    assert report["findings"][0]["name"] == "/admin/payments"
    assert report["findings"][0]["required_minimum"] == 3
    assert "Acceptance Coverage Report" in module.render_markdown(report)


def test_acceptance_report_includes_global_surface_findings() -> None:
    module = _load_module()
    manifest = {
        "title": "fixture",
        "date": "2026-06-28",
        "routes": [],
        "global_surfaces": [
            {
                "surface": "admin shell",
                "workflows": ["Open drawer", "Switch tenant"],
                "controls": {"buttons": ["Open menu"], "inputs": [], "modals": []},
                "states": ["offline"],
                "risk_edges": ["Wrong tenant", "Stale session"],
                "acceptance": ["Drawer opens"],
            }
        ],
    }

    findings = module.acceptance_findings(manifest)

    assert len(findings) == 1
    assert findings[0].inventory_type == "global_surface"
    assert findings[0].name == "admin shell"


def test_acceptance_report_passes_when_criteria_cover_workflows_and_risks() -> None:
    module = _load_module()
    manifest = {
        "title": "fixture",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/coach/today",
                "workflows": ["Review today", "Move date"],
                "controls": {"buttons": ["Previous", "Next"], "inputs": [], "modals": []},
                "states": ["loading", "empty"],
                "risk_edges": ["Stale date"],
                "acceptance": ["Today loads", "Date controls update route"],
            }
        ],
        "global_surfaces": [],
    }

    assert module.build_report(manifest)["finding_count"] == 0


def test_acceptance_report_cli_can_fail_on_gaps(tmp_path: Path, capsys) -> None:
    module = _load_module()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "title": "fixture",
                "date": "2026-06-28",
                "routes": [
                    {
                        "route": "/parent/payments",
                        "workflows": ["Pay", "Portal"],
                        "controls": {"buttons": ["Pay"], "inputs": [], "modals": []},
                        "states": ["loading"],
                        "risk_edges": ["Double pay"],
                        "acceptance": ["Pay starts"],
                    }
                ],
                "global_surfaces": [],
            }
        )
    )

    result = module.main(
        [
            "--manifest",
            str(manifest_path),
            "--format",
            "json",
            "--fail-on-gaps",
        ]
    )

    assert result == 1
    assert json.loads(capsys.readouterr().out)["finding_count"] == 1


def test_current_inventory_manifest_has_no_acceptance_coverage_findings() -> None:
    module = _load_module()
    manifest = module.load_manifest(MANIFEST)
    report = module.build_report(manifest)
    all_acceptance = "\n".join(
        item
        for entry in [*manifest["routes"], *manifest["global_surfaces"]]
        for item in entry["acceptance"]
    )

    assert report["routes"] == 70
    assert report["global_surfaces"] == 4
    assert report["finding_count"] == 0
    assert report["summary"]["routes_with_acceptance_below_workflows"] == 0
    assert report["summary"]["routes_with_acceptance_below_risks"] == 0
    assert "Workflow evidence:" in all_acceptance
    assert "Risk evidence:" in all_acceptance
