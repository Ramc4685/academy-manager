"""Unit tests for static inventory gap detection."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = (
    Path(__file__).resolve().parents[4] / "scripts" / "dev" / "audit_inventory_static_gaps.py"
)
REPO_ROOT = Path(__file__).resolve().parents[4]
MANIFEST = REPO_ROOT / "docs" / "qa" / "2026-06-28-production-scale-local-inventory-manifest.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "audit_inventory_static_gaps_for_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_static_gap_scanner_flags_missing_controls_and_states(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "frontend" / "app" / "example" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
export default function Example() {
  const isLoading = false;
  const isError = false;
  if (isLoading) return <p>Loading...</p>;
  if (isError) return <button onClick={() => null}>Retry</button>;
  return <input required aria-invalid={false} />;
}
"""
    )
    manifest = {
        "title": "fixture",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/example",
                "source": "frontend/app/example/page.tsx",
                "controls": {"buttons": [], "inputs": [], "modals": []},
                "states": ["default"],
            }
        ],
    }

    evidence = module.scan_manifest(manifest, repo_root=tmp_path)
    report = module.build_report(manifest, evidence)

    categories = {gap["category"] for gap in report["gaps"]}
    assert "controls.buttons" in categories
    assert "controls.inputs" in categories
    assert "states.loading" in categories
    assert "states.error" in categories
    assert "states.validation" in categories


def test_static_gap_scanner_accepts_manifest_acknowledgement(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "frontend" / "app" / "example" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
export default function Example() {
  return <button onClick={() => null}>Save</button>;
}
"""
    )
    manifest = {
        "title": "fixture",
        "date": "2026-06-28",
        "routes": [
            {
                "route": "/example",
                "source": "frontend/app/example/page.tsx",
                "controls": {"buttons": ["Save"], "inputs": [], "modals": []},
                "states": ["default"],
            }
        ],
    }

    evidence = module.scan_manifest(manifest, repo_root=tmp_path)

    assert module.flatten_gaps(evidence) == []


def test_static_gap_scanner_reports_potential_control_undercounts(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "frontend" / "app" / "example" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
export default function Example() {
  return <>
    <button onClick={() => null}>Save</button>
    <button onClick={() => null}>Delete</button>
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
                "source": "frontend/app/example/page.tsx",
                "controls": {"buttons": ["Save"], "inputs": [], "modals": []},
                "states": ["default"],
            }
        ],
    }

    evidence = module.scan_manifest(manifest, repo_root=tmp_path)
    report = module.build_report(manifest, evidence)

    assert report["gap_count"] == 0
    assert report["potential_under_count_count"] == 1
    assert report["potential_under_counts"][0]["category"] == "controls.buttons"
    assert "Potential Control Undercounts" in module.render_markdown(report)


def test_static_gap_scanner_cli_fails_on_gaps(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "frontend" / "app" / "example" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("export default function Example() { return <input />; }\n")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "title": "fixture",
                "date": "2026-06-28",
                "routes": [
                    {
                        "route": "/example",
                        "source": "frontend/app/example/page.tsx",
                        "controls": {"buttons": [], "inputs": [], "modals": []},
                        "states": ["default"],
                    }
                ],
            }
        )
    )

    result = module.main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
            "--fail-on-gaps",
        ]
    )

    assert result == 1
    assert json.loads(capsys.readouterr().out)["gap_count"] == 1


def test_static_gap_scanner_cli_can_fail_on_potential_undercounts(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    source = tmp_path / "frontend" / "app" / "example" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        """
export default function Example() {
  return <>
    <button onClick={() => null}>Save</button>
    <button onClick={() => null}>Delete</button>
  </>;
}
"""
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "title": "fixture",
                "date": "2026-06-28",
                "routes": [
                    {
                        "route": "/example",
                        "source": "frontend/app/example/page.tsx",
                        "controls": {"buttons": ["Save"], "inputs": [], "modals": []},
                        "states": ["default"],
                    }
                ],
            }
        )
    )

    result = module.main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
            "--fail-on-undercounts",
        ]
    )

    assert result == 1
    assert json.loads(capsys.readouterr().out)["potential_under_count_count"] == 1


def test_current_inventory_manifest_has_no_static_source_gaps() -> None:
    module = _load_module()
    manifest = module.load_manifest(MANIFEST)
    evidence = module.scan_manifest(manifest, repo_root=REPO_ROOT)
    report = module.build_report(manifest, evidence)

    assert report["gap_count"] == 0
