#!/usr/bin/env python3
"""Render the production-scale audit manifest as a reviewable coverage matrix."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(
    "docs/qa/2026-06-28-production-scale-local-inventory-manifest.json"
)


@dataclass(frozen=True)
class RoleCoverage:
    role: str
    routes: int
    workflows: int
    buttons: int
    inputs: int
    modals: int
    states: int
    risk_edges: int
    acceptance: int


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")
    return json.loads(path.read_text())


def role_coverage(manifest: dict[str, Any]) -> list[RoleCoverage]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in manifest.get("routes", []):
        grouped[route["role"]].append(route)

    coverage = []
    for role, routes in sorted(grouped.items()):
        coverage.append(
            RoleCoverage(
                role=role,
                routes=len(routes),
                workflows=sum(len(route["workflows"]) for route in routes),
                buttons=sum(len(route["controls"]["buttons"]) for route in routes),
                inputs=sum(len(route["controls"]["inputs"]) for route in routes),
                modals=sum(len(route["controls"]["modals"]) for route in routes),
                states=sum(len(route["states"]) for route in routes),
                risk_edges=sum(len(route["risk_edges"]) for route in routes),
                acceptance=sum(len(route["acceptance"]) for route in routes),
            )
        )
    return coverage


def render_markdown(manifest: dict[str, Any]) -> str:
    routes = manifest.get("routes", [])
    global_surfaces = manifest.get("global_surfaces", [])
    lines = [
        "# Production-Scale Local Inventory Coverage Matrix",
        "",
        f"- Manifest: {manifest.get('title', 'unknown')}",
        f"- Date: {manifest.get('date', 'unknown')}",
        f"- Routes: {len(routes)}",
        f"- Global surfaces: {len(global_surfaces)}",
        "",
        "## Role Coverage",
        "",
        "| Role | Routes | Workflows | Buttons | Inputs | Modals | States | Risks | Acceptance |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for coverage in role_coverage(manifest):
        lines.append(
            f"| {coverage.role} | {coverage.routes} | {coverage.workflows} | "
            f"{coverage.buttons} | {coverage.inputs} | {coverage.modals} | "
            f"{coverage.states} | {coverage.risk_edges} | {coverage.acceptance} |"
        )

    lines.extend(
        [
            "",
            "## Route Matrix",
            "",
            "| Route | Role | Workflows | Buttons | Inputs | Modals | States | Risks | Acceptance |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for route in sorted(routes, key=lambda item: (item["role"], item["route"])):
        lines.append(
            f"| `{route['route']}` | {route['role']} | {len(route['workflows'])} | "
            f"{len(route['controls']['buttons'])} | {len(route['controls']['inputs'])} | "
            f"{len(route['controls']['modals'])} | {len(route['states'])} | "
            f"{len(route['risk_edges'])} | {len(route['acceptance'])} |"
        )
    if global_surfaces:
        lines.extend(
            [
                "",
                "## Global Surface Matrix",
                "",
                "| Surface | Roles | Sources | Workflows | Buttons | Inputs | Modals | States | Risks | Acceptance |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for surface in sorted(global_surfaces, key=lambda item: item["surface"]):
            controls = surface["controls"]
            lines.append(
                f"| `{surface['surface']}` | {', '.join(surface['roles'])} | "
                f"{len(surface['sources'])} | {len(surface['workflows'])} | "
                f"{len(controls['buttons'])} | {len(controls['inputs'])} | "
                f"{len(controls['modals'])} | {len(surface['states'])} | "
                f"{len(surface['risk_edges'])} | {len(surface['acceptance'])} |"
            )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summary = render_markdown(load_manifest(args.manifest))
    if args.output:
        args.output.write_text(summary + "\n")
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
