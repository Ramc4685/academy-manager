#!/usr/bin/env python3
"""Report acceptance-criteria coverage across the audit inventory manifest."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(
    "docs/qa/2026-06-28-production-scale-local-inventory-manifest.json"
)


@dataclass(frozen=True)
class AcceptanceFinding:
    inventory_type: str
    name: str
    workflows: int
    controls: int
    states: int
    risk_edges: int
    acceptance: int
    required_minimum: int
    message: str


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")
    return json.loads(path.read_text())


def acceptance_findings(manifest: dict[str, Any]) -> list[AcceptanceFinding]:
    findings: list[AcceptanceFinding] = []
    for route in manifest.get("routes", []):
        finding = _finding_for_entry("route", route["route"], route)
        if finding:
            findings.append(finding)
    for surface in manifest.get("global_surfaces", []):
        finding = _finding_for_entry("global_surface", surface["surface"], surface)
        if finding:
            findings.append(finding)
    return findings


def _finding_for_entry(
    inventory_type: str,
    name: str,
    entry: dict[str, Any],
) -> AcceptanceFinding | None:
    workflows = len(entry["workflows"])
    controls = sum(
        len(entry["controls"][kind]) for kind in ("buttons", "inputs", "modals")
    )
    states = len(entry["states"])
    risk_edges = len(entry["risk_edges"])
    acceptance = len(entry["acceptance"])
    required_minimum = max(workflows, risk_edges)
    if acceptance >= required_minimum:
        return None
    return AcceptanceFinding(
        inventory_type=inventory_type,
        name=name,
        workflows=workflows,
        controls=controls,
        states=states,
        risk_edges=risk_edges,
        acceptance=acceptance,
        required_minimum=required_minimum,
        message=(
            "Acceptance criteria are fewer than the larger of workflows and "
            "risk edges; real-user execution needs explicit pass criteria for "
            "the missing coverage."
        ),
    )


def build_report(manifest: dict[str, Any]) -> dict[str, Any]:
    findings = acceptance_findings(manifest)
    routes = manifest.get("routes", [])
    global_surfaces = manifest.get("global_surfaces", [])
    return {
        "title": "Production-Scale Local Acceptance Coverage Report",
        "manifest": manifest.get("title", "unknown"),
        "date": manifest.get("date", "unknown"),
        "routes": len(routes),
        "global_surfaces": len(global_surfaces),
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
        "summary": {
            "routes_with_acceptance_below_workflows": sum(
                len(route["acceptance"]) < len(route["workflows"]) for route in routes
            ),
            "routes_with_acceptance_below_risks": sum(
                len(route["acceptance"]) < len(route["risk_edges"]) for route in routes
            ),
            "global_surfaces_with_acceptance_below_workflows": sum(
                len(surface["acceptance"]) < len(surface["workflows"])
                for surface in global_surfaces
            ),
            "global_surfaces_with_acceptance_below_risks": sum(
                len(surface["acceptance"]) < len(surface["risk_edges"])
                for surface in global_surfaces
            ),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Production-Scale Local Acceptance Coverage Report",
        "",
        f"- Manifest: {report['manifest']}",
        f"- Date: {report['date']}",
        f"- Routes: {report['routes']}",
        f"- Global surfaces: {report['global_surfaces']}",
        f"- Findings: {report['finding_count']}",
        f"- Routes below workflow count: {summary['routes_with_acceptance_below_workflows']}",
        f"- Routes below risk count: {summary['routes_with_acceptance_below_risks']}",
        f"- Global surfaces below workflow count: {summary['global_surfaces_with_acceptance_below_workflows']}",
        f"- Global surfaces below risk count: {summary['global_surfaces_with_acceptance_below_risks']}",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.append("No acceptance coverage gaps found.")
    else:
        lines.extend(
            [
                "These findings are documentation gaps, not application bugs. They",
                "identify inventory entries where the real-user checklist has less",
                "explicit pass/fail language than the workflows or risk edges imply.",
                "",
                "| Type | Name | Workflows | Controls | States | Risks | Acceptance | Required |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for finding in report["findings"]:
            lines.append(
                f"| {finding['inventory_type']} | `{finding['name']}` | "
                f"{finding['workflows']} | {finding['controls']} | "
                f"{finding['states']} | {finding['risk_edges']} | "
                f"{finding['acceptance']} | {finding['required_minimum']} |"
            )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument(
        "--fail-on-gaps",
        action="store_true",
        help="Exit non-zero if acceptance coverage findings are present.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_report(load_manifest(args.manifest))
    rendered = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.write_text(rendered + "\n")
    else:
        print(rendered)
    return 1 if args.fail_on_gaps and report["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
