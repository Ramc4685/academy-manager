"""Unit tests for local-auth audit artifact bundle helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_artifacts_module() -> ModuleType:
    script_dir = Path(__file__).resolve().parents[4] / "scripts" / "dev"
    script_path = script_dir / "prepare_local_auth_audit_artifacts.py"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    spec = importlib.util.spec_from_file_location(
        "prepare_local_auth_audit_artifacts_for_test", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_artifact_paths_use_expected_evidence_filenames() -> None:
    module = _load_artifacts_module()
    paths = module.artifact_paths(Path("/tmp/evidence"))

    assert paths == {
        "readiness": Path("/tmp/evidence/audit-readiness.md"),
        "coverage_matrix": Path("/tmp/evidence/inventory-coverage-matrix.md"),
        "static_gaps": Path("/tmp/evidence/inventory-static-gaps.md"),
        "acceptance_coverage": Path("/tmp/evidence/inventory-acceptance-coverage.md"),
        "control_evidence": Path("/tmp/evidence/inventory-control-evidence.md"),
        "audit_gate": Path("/tmp/evidence/inventory-audit-gate.md"),
        "checklist": Path("/tmp/evidence/inventory-checklist.md"),
        "audit_summary": Path("/tmp/evidence/audit-summary.md"),
        "index": Path("/tmp/evidence/index.md"),
    }


def test_render_index_lists_artifacts_and_readiness_result() -> None:
    module = _load_artifacts_module()
    text = module.render_index(
        {
            "readiness": Path("/tmp/evidence/audit-readiness.md"),
            "coverage_matrix": Path("/tmp/evidence/inventory-coverage-matrix.md"),
            "static_gaps": Path("/tmp/evidence/inventory-static-gaps.md"),
            "acceptance_coverage": Path("/tmp/evidence/inventory-acceptance-coverage.md"),
            "control_evidence": Path("/tmp/evidence/inventory-control-evidence.md"),
            "audit_gate": Path("/tmp/evidence/inventory-audit-gate.md"),
            "checklist": Path("/tmp/evidence/inventory-checklist.md"),
            "audit_summary": Path("/tmp/evidence/audit-summary.md"),
            "index": Path("/tmp/evidence/index.md"),
        },
        readiness_result="READY_WITH_WARNINGS",
        gate_result="BLOCKED",
    )

    assert "# Local Auth Audit Artifact Bundle" in text
    assert "- Gate result: BLOCKED" in text
    assert "- Readiness result: READY_WITH_WARNINGS" in text
    assert "`readiness`: `/tmp/evidence/audit-readiness.md`" in text
    assert "`coverage_matrix`: `/tmp/evidence/inventory-coverage-matrix.md`" in text
    assert "`static_gaps`: `/tmp/evidence/inventory-static-gaps.md`" in text
    assert "`acceptance_coverage`: `/tmp/evidence/inventory-acceptance-coverage.md`" in text
    assert "`control_evidence`: `/tmp/evidence/inventory-control-evidence.md`" in text
    assert "`audit_gate`: `/tmp/evidence/inventory-audit-gate.md`" in text
    assert "`checklist`: `/tmp/evidence/inventory-checklist.md`" in text
    assert "`audit_summary`: `/tmp/evidence/audit-summary.md`" in text
    assert "`index`:" not in text
