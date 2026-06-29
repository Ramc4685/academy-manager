#!/usr/bin/env python3
"""Compare the route inventory manifest against static frontend route evidence.

This is a conservative source scanner. It does not prove browser behavior, but
it catches manifest omissions where a route source clearly exposes controls or
state branches that the real-user checklist must cover.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(
    "docs/qa/2026-06-28-production-scale-local-inventory-manifest.json"
)


@dataclass(frozen=True)
class Finding:
    category: str
    route: str
    source: str
    message: str
    evidence: list[str]


@dataclass(frozen=True)
class RouteEvidence:
    route: str
    source: str
    detected_controls: dict[str, list[str]]
    detected_states: dict[str, list[str]]
    gaps: list[Finding]
    potential_under_counts: list[Finding]


CONTROL_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "buttons": (
        re.compile(r"<(?:button|Button|[A-Za-z0-9_.]*Button)\b"),
        re.compile(r"\bonClick\s*="),
        re.compile(r"role=[\"']button[\"']"),
    ),
    "inputs": (
        re.compile(r"<(?:input|Input|textarea|Textarea|select|Select)\b"),
        re.compile(
            r"type=[\"'](?:checkbox|date|email|number|password|radio|search|tel|text)[\"']"
        ),
    ),
    "modals": (re.compile(r"\b(?:AlertDialog|Dialog|Drawer|Modal|Popover|Sheet)\b"),),
}

CONTROL_COUNT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "buttons": (
        re.compile(r"<(?:button|Button|[A-Za-z0-9_.]*Button)\b"),
        re.compile(r"role=[\"']button[\"']"),
    ),
    "inputs": (
        re.compile(r"<(?:input|Input|textarea|Textarea|select|Select)\b"),
    ),
    "modals": (
        re.compile(r"<(?:AlertDialog|Dialog|Drawer|Modal|Popover|Sheet)\.Root\b"),
        re.compile(r"<(?:AlertDialog|Dialog|Drawer|Modal|Popover|Sheet)(?:\s|>)"),
    ),
}

STATE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "loading": (
        re.compile(r"\b(?:isLoading|loading|Loading|Skeleton|animate-pulse)\b"),
    ),
    "error": (re.compile(r"\b(?:isError|error|Error|Failed|Retry|refetch)\b"),),
    "empty": (
        re.compile(r"\b(?:empty|Empty)\b"),
        re.compile(r"\.length\s*===\s*0"),
        re.compile(r"\bNo [A-Za-z ]+(?:found|yet|available)\b"),
    ),
    "validation": (
        re.compile(r"\b(?:required|invalid|validation|aria-invalid|setError)\b"),
    ),
    "access denied": (
        re.compile(r"\b(?:access denied|forbidden|unauthorized)\b", re.IGNORECASE),
    ),
    "not found": (re.compile(r"\b(?:notFound|not found|404)\b", re.IGNORECASE),),
}


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")
    return json.loads(path.read_text())


def scan_manifest(manifest: dict[str, Any], *, repo_root: Path) -> list[RouteEvidence]:
    evidence = []
    for route in manifest.get("routes", []):
        evidence.append(scan_route(route, repo_root=repo_root))
    return evidence


def scan_route(route: dict[str, Any], *, repo_root: Path) -> RouteEvidence:
    source = route["source"]
    source_path = repo_root / source
    text = source_path.read_text() if source_path.exists() else ""
    detected_controls = {
        control: _matching_lines(text, patterns)
        for control, patterns in CONTROL_PATTERNS.items()
    }
    counted_controls = {
        control: _dedupe_component_evidence(_matching_lines(text, patterns))
        for control, patterns in CONTROL_COUNT_PATTERNS.items()
    }
    detected_states = {
        state: _matching_lines(text, patterns)
        for state, patterns in STATE_PATTERNS.items()
    }
    gaps: list[Finding] = []
    potential_under_counts: list[Finding] = []

    manifest_controls = route.get("controls", {})
    for control, matches in detected_controls.items():
        manifest_items = manifest_controls.get(control, [])
        if matches and not manifest_items:
            gaps.append(
                Finding(
                    category=f"controls.{control}",
                    route=route["route"],
                    source=source,
                    message=(
                        f"Static source exposes {control}, but manifest lists none."
                    ),
                    evidence=matches[:5],
                )
            )
        counted_matches = counted_controls.get(control, matches)
        if manifest_items and len(counted_matches) > len(manifest_items):
            potential_under_counts.append(
                Finding(
                    category=f"controls.{control}",
                    route=route["route"],
                    source=source,
                    message=(
                        f"Static source has {len(counted_matches)} semantic {control} evidence lines, "
                        f"but manifest names {len(manifest_items)}."
                    ),
                    evidence=counted_matches[:8],
                )
            )

    manifest_states = " ".join(route.get("states", [])).lower()
    for state, matches in detected_states.items():
        if matches and state not in manifest_states:
            gaps.append(
                Finding(
                    category=f"states.{state}",
                    route=route["route"],
                    source=source,
                    message=f"Static source exposes {state} state evidence, but manifest does not list it.",
                    evidence=matches[:5],
                )
            )

    return RouteEvidence(
        route=route["route"],
        source=source,
        detected_controls=detected_controls,
        detected_states=detected_states,
        gaps=gaps,
        potential_under_counts=potential_under_counts,
    )


def _matching_lines(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    matches = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("//", "/*", "*")):
            continue
        if any(pattern.search(stripped) for pattern in patterns):
            matches.append(f"L{line_number}: {stripped[:160]}")
    return matches


def _dedupe_component_evidence(matches: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in matches:
        normalized = re.sub(r"\s+", " ", re.sub(r"^L\d+:\s*", "", item)).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item)
    return deduped


def flatten_gaps(route_evidence: list[RouteEvidence]) -> list[Finding]:
    return [gap for route in route_evidence for gap in route.gaps]


def flatten_potential_under_counts(
    route_evidence: list[RouteEvidence],
) -> list[Finding]:
    return [
        under_count
        for route in route_evidence
        for under_count in route.potential_under_counts
    ]


def build_report(
    manifest: dict[str, Any],
    route_evidence: list[RouteEvidence],
) -> dict[str, Any]:
    gaps = flatten_gaps(route_evidence)
    potential_under_counts = flatten_potential_under_counts(route_evidence)
    return {
        "title": "Production-Scale Local Static Inventory Gap Report",
        "manifest": manifest.get("title", "unknown"),
        "date": manifest.get("date", "unknown"),
        "routes": len(route_evidence),
        "global_surfaces": len(manifest.get("global_surfaces", [])),
        "gap_count": len(gaps),
        "potential_under_count_count": len(potential_under_counts),
        "gaps": [asdict(gap) for gap in gaps],
        "potential_under_counts": [
            asdict(under_count) for under_count in potential_under_counts
        ],
        "route_evidence": [
            {
                "route": route.route,
                "source": route.source,
                "detected_controls": {
                    key: len(value) for key, value in route.detected_controls.items()
                },
                "detected_states": {
                    key: len(value) for key, value in route.detected_states.items()
                },
                "gap_count": len(route.gaps),
                "potential_under_count_count": len(route.potential_under_counts),
            }
            for route in route_evidence
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Production-Scale Local Static Inventory Gap Report",
        "",
        f"- Manifest: {report['manifest']}",
        f"- Date: {report['date']}",
        f"- Routes scanned: {report['routes']}",
        f"- Global surfaces inventoried: {report['global_surfaces']}",
        f"- Gaps: {report['gap_count']}",
        f"- Potential control undercounts: {report['potential_under_count_count']}",
        "",
        "## Gaps",
        "",
    ]
    if not report["gaps"]:
        lines.append("No static inventory gaps found.")
    else:
        for gap in report["gaps"]:
            lines.extend(
                [
                    f"### `{gap['route']}` - {gap['category']}",
                    "",
                    f"- Source: `{gap['source']}`",
                    f"- Issue: {gap['message']}",
                    "- Evidence:",
                    *[f"  - `{item}`" for item in gap["evidence"]],
                    "",
                ]
            )

    lines.extend(["", "## Potential Control Undercounts", ""])
    if not report["potential_under_counts"]:
        lines.append("No potential static control undercounts found.")
    else:
        lines.extend(
            [
                "These are conservative source-count warnings. Review manually before",
                "treating them as confirmed missing controls because local component",
                "definitions and repeated state branches can inflate raw evidence counts.",
                "",
            ]
        )
        for item in report["potential_under_counts"]:
            lines.extend(
                [
                    f"### `{item['route']}` - {item['category']}",
                    "",
                    f"- Source: `{item['source']}`",
                    f"- Issue: {item['message']}",
                    "- Evidence:",
                    *[f"  - `{line}`" for line in item["evidence"]],
                    "",
                ]
            )

    lines.extend(
        [
            "",
            "## Route Evidence Counts",
            "",
            "| Route | Buttons | Inputs | Modals | Loading | Error | Empty | Validation | Access Denied | Not Found | Gaps |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for route in report["route_evidence"]:
        controls = route["detected_controls"]
        states = route["detected_states"]
        lines.append(
            f"| `{route['route']}` | {controls['buttons']} | {controls['inputs']} | "
            f"{controls['modals']} | {states['loading']} | {states['error']} | "
            f"{states['empty']} | {states['validation']} | {states['access denied']} | "
            f"{states['not found']} | {route['gap_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument(
        "--fail-on-gaps",
        action="store_true",
        help="Exit non-zero if static manifest gaps are detected.",
    )
    parser.add_argument(
        "--fail-on-undercounts",
        action="store_true",
        help="Exit non-zero if potential control undercounts are detected.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    manifest = load_manifest(args.manifest)
    route_evidence = scan_manifest(manifest, repo_root=repo_root)
    report = build_report(manifest, route_evidence)
    rendered = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.write_text(rendered + "\n")
    else:
        print(rendered)
    if args.fail_on_gaps and report["gap_count"]:
        return 1
    if args.fail_on_undercounts and report["potential_under_count_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
