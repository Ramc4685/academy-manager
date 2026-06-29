#!/usr/bin/env python3
"""Generate a tester checklist from the production-scale audit manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(
    "docs/qa/2026-06-28-production-scale-local-inventory-manifest.json"
)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")
    return json.loads(path.read_text())


def render_markdown(manifest: dict[str, Any]) -> str:
    routes_by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in manifest.get("routes", []):
        routes_by_role[route["role"]].append(route)

    lines = [
        "# Production-Scale Local Real-User Inventory Checklist",
        "",
        f"- Manifest: {manifest.get('title', 'unknown')}",
        f"- Date: {manifest.get('date', 'unknown')}",
        f"- Routes: {len(manifest.get('routes', []))}",
        f"- Global surfaces: {len(manifest.get('global_surfaces', []))}",
        "- Evidence root: /tmp/academy-manager-local/evidence/20260628-production-scale-audit",
        "",
        "Use this checklist during the approved real-user browser run. Mark a route",
        "complete only after authorized navigation, expected states, primary controls,",
        "risk edges, and acceptance criteria have evidence or an explicit blocked note.",
        "",
    ]

    for role in sorted(routes_by_role):
        lines.extend([f"## {role.title()} Routes", ""])
        for route in sorted(routes_by_role[role], key=lambda item: item["route"]):
            lines.extend(_route_section(route))

    global_surfaces = manifest.get("global_surfaces", [])
    if global_surfaces:
        lines.extend(["## Global Shell Surfaces", ""])
        for surface in sorted(global_surfaces, key=lambda item: item["surface"]):
            lines.extend(_global_surface_section(surface))

    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    checklist = render_markdown(load_manifest(args.manifest))
    if args.output:
        args.output.write_text(checklist + "\n")
    else:
        print(checklist)
    return 0


def _route_section(route: dict[str, Any]) -> list[str]:
    controls = route["controls"]
    lines = [
        f"### `{route['route']}`",
        "",
        f"- Source: `{route['source']}`",
        f"- Role: `{route['role']}`",
        "- Result: [ ] pass [ ] fail [ ] blocked",
        "- Evidence path:",
        "- Seeded account:",
        "- Notes:",
        "",
        "Workflows:",
        *_checklist_items(route["workflows"]),
        "",
        "Controls:",
        *_checklist_items(_control_items(controls)),
        "",
        "States:",
        *_checklist_items(route["states"]),
        "",
        "Risk Edges:",
        *_checklist_items(route["risk_edges"]),
        "",
        "Acceptance Criteria:",
        *_checklist_items(route["acceptance"]),
        "",
    ]
    return lines


def _global_surface_section(surface: dict[str, Any]) -> list[str]:
    controls = surface["controls"]
    lines = [
        f"### `{surface['surface']}`",
        "",
        f"- Roles: `{', '.join(surface['roles'])}`",
        "- Sources:",
        *[f"  - `{source}`" for source in surface["sources"]],
        "- Result: [ ] pass [ ] fail [ ] blocked",
        "- Evidence path:",
        "- Seeded account:",
        "- Notes:",
        "",
        "Workflows:",
        *_checklist_items(surface["workflows"]),
        "",
        "Controls:",
        *_checklist_items(_control_items(controls)),
        "",
        "States:",
        *_checklist_items(surface["states"]),
        "",
        "Risk Edges:",
        *_checklist_items(surface["risk_edges"]),
        "",
        "Acceptance Criteria:",
        *_checklist_items(surface["acceptance"]),
        "",
    ]
    return lines


def _control_items(controls: dict[str, list[str]]) -> list[str]:
    items: list[str] = []
    for control_type in ("buttons", "inputs", "modals"):
        values = controls.get(control_type, [])
        if values:
            items.extend(f"{control_type}: {value}" for value in values)
        else:
            items.append(f"{control_type}: none exposed")
    return items


def _checklist_items(items: list[str]) -> list[str]:
    return [f"- [ ] {item}" for item in items]


if __name__ == "__main__":
    raise SystemExit(main())
