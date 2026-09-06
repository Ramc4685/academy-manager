"""Unit tests for source-derived inventory control evidence."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parents[4] / "scripts" / "dev"
SCRIPT_PATH = SCRIPT_DIR / "audit_inventory_control_evidence.py"
REPO_ROOT = Path(__file__).resolve().parents[4]
MANIFEST = REPO_ROOT / "docs" / "qa" / "2026-06-28-production-scale-local-inventory-manifest.json"


def _load_module() -> ModuleType:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(
        "audit_inventory_control_evidence_for_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_control_evidence_report_includes_manifest_and_source_lines(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "frontend" / "app" / "example" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
export default function Example() {
  return <>
    <button onClick={() => null}>Save</button>
    <input required />
  </>;
}
"""
    )
    manifest = {
        "title": "fixture",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/example",
                "role": "admin",
                "source": "frontend/app/example/page.tsx",
                "controls": {"buttons": ["Save"], "inputs": ["Name"], "modals": []},
            }
        ],
    }

    report = module.build_report(manifest, repo_root=tmp_path)
    markdown = module.render_markdown(report)

    assert report["routes"] == 1
    assert report["totals"]["buttons"] == 1
    assert report["totals"]["inputs"] == 1
    assert report["route_evidence"][0]["controls"]["buttons"]["manifest"] == ["Save"]
    assert "L4: <button onClick={() => null}>Save</button>" in markdown
    assert "Manifest entries:" in markdown


def test_control_evidence_cli_outputs_json_for_current_manifest(capsys) -> None:
    module = _load_module()

    assert (
        module.main(
            [
                "--manifest",
                str(MANIFEST),
                "--repo-root",
                str(REPO_ROOT),
                "--format",
                "json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)

    assert report["routes"] == 91
    assert report["totals"]["buttons"] > 0
    assert report["totals"]["inputs"] > 0
    assert report["totals"]["modals"] >= 0
