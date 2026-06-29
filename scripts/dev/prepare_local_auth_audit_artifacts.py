#!/usr/bin/env python3
"""Prepare read-only local-auth audit handoff artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pymongo import MongoClient

import audit_inventory_acceptance_coverage
import audit_inventory_control_evidence
import audit_inventory_gate
import audit_inventory_static_gaps
import check_local_auth_audit_readiness
import export_local_auth_inventory_env
import generate_inventory_checklist
import scale_blno_staging
import summarize_inventory_manifest
import summarize_local_auth_audit

DEFAULT_OUTPUT_DIR = check_local_auth_audit_readiness.DEFAULT_EVIDENCE_DIR
DEFAULT_MANIFEST = summarize_inventory_manifest.DEFAULT_MANIFEST


def artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "readiness": output_dir / "audit-readiness.md",
        "coverage_matrix": output_dir / "inventory-coverage-matrix.md",
        "static_gaps": output_dir / "inventory-static-gaps.md",
        "acceptance_coverage": output_dir / "inventory-acceptance-coverage.md",
        "control_evidence": output_dir / "inventory-control-evidence.md",
        "audit_gate": output_dir / "inventory-audit-gate.md",
        "checklist": output_dir / "inventory-checklist.md",
        "audit_summary": output_dir / "audit-summary.md",
        "index": output_dir / "index.md",
    }


def render_index(
    artifacts: dict[str, Path], *, readiness_result: str, gate_result: str
) -> str:
    lines = [
        "# Local Auth Audit Artifact Bundle",
        "",
        f"- Gate result: {gate_result}",
        f"- Readiness result: {readiness_result}",
        "",
        "## Files",
        "",
    ]
    for name, path in artifacts.items():
        if name == "index":
            continue
        lines.append(f"- `{name}`: `{path}`")
    return "\n".join(lines)


def prepare_artifacts(
    *,
    base_url: str,
    mongo_url: str,
    db_name: str,
    manifest_path: Path,
    output_dir: Path,
) -> tuple[dict[str, Path], str, str]:
    check_local_auth_audit_readiness.assert_local_base_url(base_url)
    export_local_auth_inventory_env.assert_local_mongo_url(mongo_url)
    export_local_auth_inventory_env.assert_staging_db_name(db_name)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = artifact_paths(output_dir)

    manifest = summarize_inventory_manifest.load_manifest(manifest_path)
    artifacts["coverage_matrix"].write_text(
        summarize_inventory_manifest.render_markdown(manifest) + "\n"
    )
    static_evidence = audit_inventory_static_gaps.scan_manifest(
        manifest, repo_root=Path(".").resolve()
    )
    static_report = audit_inventory_static_gaps.build_report(manifest, static_evidence)
    artifacts["static_gaps"].write_text(
        audit_inventory_static_gaps.render_markdown(static_report) + "\n"
    )
    acceptance_report = audit_inventory_acceptance_coverage.build_report(manifest)
    artifacts["acceptance_coverage"].write_text(
        audit_inventory_acceptance_coverage.render_markdown(acceptance_report) + "\n"
    )
    control_evidence_report = audit_inventory_control_evidence.build_report(
        manifest, repo_root=Path(".").resolve()
    )
    artifacts["control_evidence"].write_text(
        audit_inventory_control_evidence.render_markdown(control_evidence_report) + "\n"
    )
    artifacts["checklist"].write_text(
        generate_inventory_checklist.render_markdown(manifest) + "\n"
    )

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5_000)
    try:
        client.admin.command("ping")
        db = client[db_name]
        inventory = export_local_auth_inventory_env.build_inventory_env(db)
        cleanup_counts = scale_blno_staging.count_synthetic_scale_rows(db)
    finally:
        client.close()

    report_path = output_dir / "playwright-report.json"
    report = (
        summarize_local_auth_audit.load_report(report_path)
        if report_path.exists()
        else None
    )
    readiness_items = check_local_auth_audit_readiness.readiness_items_from_state(
        base_url=base_url,
        evidence_dir=output_dir,
        inventory=inventory,
        cleanup_counts=cleanup_counts,
        report=report,
    )
    gate_report = audit_inventory_gate.build_report(
        audit_inventory_gate.gate_items_from_state(
            manifest=manifest,
            base_url=base_url,
            evidence_dir=output_dir,
            inventory=inventory,
            cleanup_counts=cleanup_counts,
            report=report,
        )
    )
    artifacts["audit_gate"].write_text(
        audit_inventory_gate.render_markdown(gate_report) + "\n"
    )
    artifacts["readiness"].write_text(
        check_local_auth_audit_readiness.render_markdown(readiness_items) + "\n"
    )

    if report is None:
        artifacts["audit_summary"].write_text(
            "# Local Auth Audit Evidence Summary\n\nNo Playwright JSON report found yet.\n"
        )
    else:
        artifacts["audit_summary"].write_text(
            summarize_local_auth_audit.render_markdown(
                report, summarize_local_auth_audit.collect_tests(report)
            )
            + "\n"
        )

    readiness_result = _readiness_result(readiness_items)
    gate_result = str(gate_report["result"])
    artifacts["index"].write_text(
        render_index(
            artifacts, readiness_result=readiness_result, gate_result=gate_result
        )
        + "\n"
    )
    return artifacts, readiness_result, gate_result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=check_local_auth_audit_readiness.DEFAULT_BASE_URL
    )
    parser.add_argument(
        "--mongo-url", default=export_local_auth_inventory_env.DEFAULT_MONGO_URL
    )
    parser.add_argument(
        "--db-name", default=export_local_auth_inventory_env.DEFAULT_DB_NAME
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    artifacts, readiness_result, gate_result = prepare_artifacts(
        base_url=args.base_url,
        mongo_url=args.mongo_url,
        db_name=args.db_name,
        manifest_path=args.manifest,
        output_dir=args.output_dir,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "readiness_result": readiness_result,
                    "gate_result": gate_result,
                    "artifacts": {name: str(path) for name, path in artifacts.items()},
                },
                indent=2,
            )
        )
    else:
        print(
            render_index(
                artifacts, readiness_result=readiness_result, gate_result=gate_result
            )
        )
    return 0 if gate_result == "CLEAN_PASS" else 1


def _readiness_result(
    items: list[check_local_auth_audit_readiness.ReadinessItem],
) -> str:
    if any(item.status == "block" for item in items):
        return "BLOCKED"
    if any(item.status == "warn" for item in items):
        return "READY_WITH_WARNINGS"
    return "READY"


if __name__ == "__main__":
    raise SystemExit(main())
