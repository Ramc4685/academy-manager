"""Unit tests for inventory manifest coverage summaries."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_summary_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[4] / "scripts" / "dev" / "summarize_inventory_manifest.py"
    )
    spec = importlib.util.spec_from_file_location(
        "summarize_inventory_manifest_for_test", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_role_coverage_counts_controls_and_acceptance() -> None:
    module = _load_summary_module()
    manifest = {
        "routes": [
            {
                "route": "/admin",
                "role": "admin",
                "workflows": ["Dashboard", "Triage"],
                "controls": {
                    "buttons": ["Refresh", "Open"],
                    "inputs": ["Search"],
                    "modals": ["Confirm"],
                },
                "states": ["loading", "empty"],
                "risk_edges": ["Tenant mismatch"],
                "acceptance": ["Renders"],
            },
            {
                "route": "/admin/users",
                "role": "admin",
                "workflows": ["Directory"],
                "controls": {"buttons": ["Create"], "inputs": [], "modals": []},
                "states": ["loading"],
                "risk_edges": ["Duplicate email"],
                "acceptance": ["Filters work", "Errors visible"],
            },
        ]
    }

    coverage = module.role_coverage(manifest)

    assert coverage == [
        module.RoleCoverage(
            role="admin",
            routes=2,
            workflows=3,
            buttons=3,
            inputs=1,
            modals=1,
            states=3,
            risk_edges=2,
            acceptance=3,
        )
    ]


def test_render_markdown_includes_role_and_route_matrices() -> None:
    module = _load_summary_module()
    manifest = {
        "title": "Audit Manifest",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/parent/payments",
                "role": "parent",
                "workflows": ["Pay invoice"],
                "controls": {
                    "buttons": ["Pay"],
                    "inputs": ["Amount"],
                    "modals": ["Confirm payment"],
                },
                "states": ["loading", "error"],
                "risk_edges": ["Double payment"],
                "acceptance": ["Cannot double-pay"],
            }
        ],
        "global_surfaces": [
            {
                "surface": "parent shell",
                "roles": ["parent"],
                "sources": ["frontend/app/(parent)/layout.tsx"],
                "workflows": ["Navigate tabs"],
                "controls": {"buttons": ["Log out"], "inputs": [], "modals": []},
                "states": ["offline", "update available"],
                "risk_edges": ["Logout stale session"],
                "acceptance": ["Logout returns to login"],
            }
        ],
    }

    markdown = module.render_markdown(manifest)

    assert "# Production-Scale Local Inventory Coverage Matrix" in markdown
    assert "- Global surfaces: 1" in markdown
    assert "| parent | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 1 |" in markdown
    assert "| `/parent/payments` | parent | 1 | 1 | 1 | 1 | 2 | 1 | 1 |" in markdown
    assert "| `parent shell` | parent | 1 | 1 | 1 | 0 | 0 | 2 | 1 | 1 |" in markdown
