#!/usr/bin/env python3
"""Render source-derived control evidence for the audit inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import audit_inventory_static_gaps

DEFAULT_MANIFEST = audit_inventory_static_gaps.DEFAULT_MANIFEST


def load_manifest(path: Path) -> dict[str, Any]:
    return audit_inventory_static_gaps.load_manifest(path)


def build_report(manifest: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    evidence = audit_inventory_static_gaps.scan_manifest(manifest, repo_root=repo_root)
    routes_by_name = {route["route"]: route for route in manifest.get("routes", [])}
    route_reports = []
    totals = {"buttons": 0, "inputs": 0, "modals": 0}

    for route_evidence in evidence:
        manifest_route = routes_by_name[route_evidence.route]
        controls = {}
        for control_type in ("buttons", "inputs", "modals"):
            detected = route_evidence.detected_controls[control_type]
            totals[control_type] += len(detected)
            controls[control_type] = {
                "manifest": manifest_route["controls"][control_type],
                "detected_count": len(detected),
                "evidence": detected,
            }
        route_reports.append(
            {
                "route": route_evidence.route,
                "role": manifest_route["role"],
                "source": route_evidence.source,
                "controls": controls,
            }
        )

    return {
        "title": "Production-Scale Local Source Control Evidence",
        "manifest": manifest.get("title", "unknown"),
        "date": manifest.get("date", "unknown"),
        "routes": len(route_reports),
        "totals": totals,
        "route_evidence": route_reports,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Production-Scale Local Source Control Evidence",
        "",
        f"- Manifest: {report['manifest']}",
        f"- Date: {report['date']}",
        f"- Routes scanned: {report['routes']}",
        f"- Detected button lines: {report['totals']['buttons']}",
        f"- Detected input lines: {report['totals']['inputs']}",
        f"- Detected modal lines: {report['totals']['modals']}",
        "",
        "This source-derived evidence is a review aid for the approved real-user",
        "inventory. It does not prove rendered browser behavior; it identifies",
        "route-owned control evidence that must be reconciled with screenshots,",
        "traces, and checklist notes during execution.",
        "",
    ]
    for route in report["route_evidence"]:
        lines.extend(
            [
                f"## `{route['route']}`",
                "",
                f"- Role: `{route['role']}`",
                f"- Source: `{route['source']}`",
                "",
            ]
        )
        for control_type in ("buttons", "inputs", "modals"):
            control = route["controls"][control_type]
            lines.extend(
                [
                    f"### {control_type.title()}",
                    "",
                    f"- Manifest named: {len(control['manifest'])}",
                    f"- Source evidence lines: {control['detected_count']}",
                    "",
                ]
            )
            if control["manifest"]:
                lines.extend(
                    [
                        "Manifest entries:",
                        *[f"- `{item}`" for item in control["manifest"]],
                        "",
                    ]
                )
            if control["evidence"]:
                lines.extend(
                    [
                        "Source evidence:",
                        *[f"- `{item}`" for item in control["evidence"]],
                        "",
                    ]
                )
            else:
                lines.append("No direct source evidence detected.")
                lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_report(
        load_manifest(args.manifest), repo_root=args.repo_root.resolve()
    )
    rendered = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.write_text(rendered + "\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
