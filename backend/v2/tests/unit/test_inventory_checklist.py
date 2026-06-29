"""Unit tests for generated real-user inventory checklists."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_checklist_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[4] / "scripts" / "dev" / "generate_inventory_checklist.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_inventory_checklist_for_test", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checklist_includes_route_execution_fields_and_manifest_items() -> None:
    module = _load_checklist_module()
    manifest = {
        "title": "Audit Manifest",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/parent/payments",
                "role": "parent",
                "source": "frontend/app/(parent)/parent/payments/page.tsx",
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
                "surface": "parent shell navigation",
                "roles": ["parent"],
                "sources": ["frontend/app/(parent)/layout.tsx"],
                "workflows": ["Navigate tabs"],
                "controls": {"buttons": ["Log out"], "inputs": [], "modals": []},
                "states": ["offline"],
                "risk_edges": ["Stale session"],
                "acceptance": ["Logout returns to login"],
            }
        ],
    }

    checklist = module.render_markdown(manifest)

    assert "# Production-Scale Local Real-User Inventory Checklist" in checklist
    assert "### `/parent/payments`" in checklist
    assert "- Result: [ ] pass [ ] fail [ ] blocked" in checklist
    assert "- Evidence path:" in checklist
    assert "- Seeded account:" in checklist
    assert "- [ ] Pay invoice" in checklist
    assert "- [ ] buttons: Pay" in checklist
    assert "- [ ] inputs: Amount" in checklist
    assert "- [ ] modals: Confirm payment" in checklist
    assert "- [ ] Double payment" in checklist
    assert "- [ ] Cannot double-pay" in checklist
    assert "## Global Shell Surfaces" in checklist
    assert "### `parent shell navigation`" in checklist
    assert "- Roles: `parent`" in checklist
    assert "  - `frontend/app/(parent)/layout.tsx`" in checklist
    assert "- [ ] Navigate tabs" in checklist
    assert "- [ ] buttons: Log out" in checklist
    assert "- [ ] Logout returns to login" in checklist


def test_checklist_marks_empty_control_types_as_none_exposed() -> None:
    module = _load_checklist_module()
    route = {
        "route": "/api/v2/[...path]",
        "role": "proxy",
        "source": "frontend/app/api/v2/[...path]/route.ts",
        "workflows": ["Proxy request"],
        "controls": {"buttons": [], "inputs": ["Header"], "modals": []},
        "states": ["error"],
        "risk_edges": ["Header dropped"],
        "acceptance": ["Errors visible"],
    }

    section = "\n".join(module._route_section(route))

    assert "- [ ] buttons: none exposed" in section
    assert "- [ ] inputs: Header" in section
    assert "- [ ] modals: none exposed" in section
