#!/usr/bin/env python3
"""Aggregate read-only gate for the production-scale local inventory audit."""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pymongo import MongoClient

import audit_inventory_acceptance_coverage
import audit_inventory_control_evidence
import audit_inventory_static_gaps
import check_local_auth_audit_readiness
import export_local_auth_inventory_env
import scale_blno_staging
import summarize_local_auth_audit
import validate_scale_seed_safety

DEFAULT_BASE_URL = check_local_auth_audit_readiness.DEFAULT_BASE_URL
DEFAULT_EVIDENCE_DIR = check_local_auth_audit_readiness.DEFAULT_EVIDENCE_DIR
DEFAULT_MANIFEST = audit_inventory_static_gaps.DEFAULT_MANIFEST
DIRECT_ROUTE_EXCLUSIONS = {"/post-login"}
EXPECTED_SCALE_PLAN = scale_blno_staging.build_scale_plan(
    parent_count=250,
    students_per_parent=2,
    months=list(scale_blno_staging.DEFAULT_MONTHS),
)


@dataclass(frozen=True)
class GateItem:
    status: str
    name: str
    detail: str


def gate_items_from_state(
    *,
    manifest: dict[str, Any],
    base_url: str,
    evidence_dir: Path,
    inventory: Any,
    cleanup_counts: dict[str, int],
    report: dict[str, Any] | None,
) -> list[GateItem]:
    items: list[GateItem] = [
        GateItem("pass", "base_url", f"Local base URL: {base_url}"),
        GateItem("pass", "evidence_dir", str(evidence_dir)),
    ]

    items.extend(_auth_env_gate_items())
    items.extend(_scale_gate_items(cleanup_counts))
    items.extend(_dynamic_route_gate_items(inventory))
    items.extend(_static_gate_items(manifest))
    items.extend(_acceptance_gate_items(manifest))
    items.extend(_control_evidence_gate_items(manifest))
    items.extend(_playwright_gate_items(manifest, report))
    return items


def result_from_items(items: list[GateItem]) -> str:
    if any(item.status == "block" for item in items):
        return "BLOCKED"
    if any(item.status == "warn" for item in items):
        return "READY_WITH_WARNINGS"
    return "CLEAN_PASS"


def build_report(items: list[GateItem]) -> dict[str, Any]:
    return {
        "title": "Production-Scale Local Inventory Audit Gate",
        "result": result_from_items(items),
        "counts": {
            "pass": sum(item.status == "pass" for item in items),
            "warn": sum(item.status == "warn" for item in items),
            "block": sum(item.status == "block" for item in items),
        },
        "items": [asdict(item) for item in items],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Production-Scale Local Inventory Audit Gate",
        "",
        f"- Result: {report['result']}",
        f"- Passing checks: {report['counts']['pass']}",
        f"- Warnings: {report['counts']['warn']}",
        f"- Blockers: {report['counts']['block']}",
        "",
        "## Checks",
        "",
    ]
    for item in report["items"]:
        lines.append(f"- {item['status'].upper()} `{item['name']}`: {item['detail']}")
    lines.append("")
    return "\n".join(lines)


def _scale_gate_items(cleanup_counts: dict[str, int]) -> list[GateItem]:
    expected = EXPECTED_SCALE_PLAN.counts
    missing = {
        collection: expected_count - cleanup_counts.get(collection, 0)
        for collection, expected_count in expected.items()
        if cleanup_counts.get(collection, 0) < expected_count
    }
    extra = {
        collection: cleanup_counts.get(collection, 0) - expected_count
        for collection, expected_count in expected.items()
        if cleanup_counts.get(collection, 0) > expected_count
    }
    if missing:
        sample = ", ".join(
            f"{collection} missing {count}"
            for collection, count in list(missing.items())[:5]
        )
        return [
            GateItem(
                "block",
                "production_scale_rows",
                "Synthetic production-scale rows are not fully applied: " + sample,
            )
        ]
    if extra:
        sample = ", ".join(
            f"{collection} extra {count}"
            for collection, count in list(extra.items())[:5]
        )
        return [
            GateItem(
                "warn",
                "production_scale_rows",
                "Synthetic scale rows exceed expected deterministic counts: " + sample,
            )
        ]
    return [
        GateItem(
            "pass",
            "production_scale_rows",
            "Expected 250-parent synthetic scale rows are present.",
        )
    ]


def _dynamic_route_gate_items(inventory: Any) -> list[GateItem]:
    if inventory.missing:
        return [
            GateItem(
                "block",
                "dynamic_route_ids",
                "Missing env vars: " + ", ".join(inventory.missing),
            )
        ]
    return [
        GateItem(
            "pass",
            "dynamic_route_ids",
            f"All {len(inventory.values)} dynamic route env vars available.",
        )
    ]


def _auth_env_gate_items() -> list[GateItem]:
    auth_item = check_local_auth_audit_readiness.auth_env_item()
    status = "pass" if auth_item.status == "ok" else "block"
    return [GateItem(status, auth_item.name, auth_item.detail)]


def _static_gate_items(manifest: dict[str, Any]) -> list[GateItem]:
    evidence = audit_inventory_static_gaps.scan_manifest(
        manifest, repo_root=Path(".").resolve()
    )
    report = audit_inventory_static_gaps.build_report(manifest, evidence)
    items = []
    if report["gap_count"]:
        items.append(
            GateItem(
                "block",
                "static_manifest_gaps",
                f"{report['gap_count']} route source controls/states are missing from manifest.",
            )
        )
    else:
        items.append(
            GateItem(
                "pass",
                "static_manifest_gaps",
                "No source-detected route control/state category gaps.",
            )
        )
    if report["potential_under_count_count"]:
        items.append(
            GateItem(
                "warn",
                "potential_control_undercounts",
                f"{report['potential_under_count_count']} source-count warnings need real-user reconciliation.",
            )
        )
    else:
        items.append(
            GateItem(
                "pass", "potential_control_undercounts", "No source-count warnings."
            )
        )
    return items


def _acceptance_gate_items(manifest: dict[str, Any]) -> list[GateItem]:
    report = audit_inventory_acceptance_coverage.build_report(manifest)
    if report["finding_count"]:
        return [
            GateItem(
                "block",
                "acceptance_coverage",
                f"{report['finding_count']} entries have fewer acceptance criteria than workflows or risks.",
            )
        ]
    return [
        GateItem(
            "pass",
            "acceptance_coverage",
            "Acceptance criteria cover all workflow and risk counts.",
        )
    ]


def _control_evidence_gate_items(manifest: dict[str, Any]) -> list[GateItem]:
    report = audit_inventory_control_evidence.build_report(
        manifest, repo_root=Path(".").resolve()
    )
    expected_routes = len(manifest.get("routes", []))
    if report["routes"] != expected_routes:
        return [
            GateItem(
                "block",
                "control_evidence",
                f"Control evidence scanned {report['routes']} routes, expected {expected_routes}.",
            )
        ]
    return [
        GateItem(
            "pass",
            "control_evidence",
            "Source evidence scanned "
            f"{report['routes']} routes: {report['totals']['buttons']} button, "
            f"{report['totals']['inputs']} input, {report['totals']['modals']} modal lines.",
        )
    ]


def _playwright_gate_items(
    manifest: dict[str, Any], report: dict[str, Any] | None
) -> list[GateItem]:
    if report is None:
        return [
            GateItem(
                "block",
                "real_user_playwright",
                "No Playwright JSON report found; real-user inventory has not run.",
            )
        ]
    tests = summarize_local_auth_audit.collect_tests(report)
    expected_inventory_titles = _expected_inventory_test_titles(manifest)
    expected_inventory_count = len(expected_inventory_titles)
    actual_inventory_titles = _inventory_report_titles(tests)
    actual_inventory_count = sum(actual_inventory_titles.values())
    missing_titles = sorted(
        (
            collections.Counter(expected_inventory_titles) - actual_inventory_titles
        ).elements()
    )
    extra_titles = sorted(
        (
            actual_inventory_titles - collections.Counter(expected_inventory_titles)
        ).elements()
    )
    items = [
        GateItem(
            "pass",
            "playwright_report_completeness",
            f"Report includes {actual_inventory_count} expected inventory tests.",
        )
    ]
    if actual_inventory_count < expected_inventory_count:
        items[0] = GateItem(
            "block",
            "playwright_report_completeness",
            "Playwright report is missing manifest inventory tests: "
            f"found {actual_inventory_count}, expected {expected_inventory_count}.",
        )
    elif missing_titles or extra_titles:
        detail = []
        if missing_titles:
            detail.append("missing: " + "; ".join(missing_titles[:5]))
        if extra_titles:
            detail.append("unexpected: " + "; ".join(extra_titles[:5]))
        items[0] = GateItem(
            "block",
            "playwright_report_completeness",
            "Playwright report inventory tests do not match manifest: "
            + " | ".join(detail),
        )

    failed = [
        test for test in tests if test.status in {"failed", "timedOut", "interrupted"}
    ]
    skipped = [test for test in tests if test.status == "skipped"]
    if failed:
        items.append(
            GateItem(
                "block",
                "real_user_playwright",
                f"{len(failed)} real-user tests failed out of {len(tests)}.",
            )
        )
        return items
    if skipped:
        items.append(
            GateItem(
                "block",
                "real_user_playwright",
                f"{len(skipped)} real-user tests skipped out of {len(tests)}.",
            )
        )
        return items
    items.append(
        GateItem(
            "pass",
            "real_user_playwright",
            f"All {len(tests)} real-user tests completed without failure or skip.",
        )
    )
    return items


def _expected_inventory_test_count(manifest: dict[str, Any]) -> int:
    return len(_expected_inventory_test_titles(manifest))


def _expected_inventory_test_titles(manifest: dict[str, Any]) -> list[str]:
    routes = manifest.get("routes", [])
    static_routes = [
        route
        for route in routes
        if "[" not in route["route"]
        and route.get("role") != "proxy"
        and route["route"] not in DIRECT_ROUTE_EXCLUSIONS
    ]
    dynamic_routes = [
        route
        for route in routes
        if "[" in route["route"] and route.get("role") != "proxy"
    ]
    shared_auth_routes = [
        route for route in static_routes if route.get("role") == "authenticated"
    ]
    titles = [
        f"public route {route['route']} renders meaningful content"
        for route in static_routes
        if route.get("role") == "public"
    ]
    for role in ("admin", "coach", "parent"):
        titles.extend(
            f"{route['route']} renders without framework errors"
            for route in static_routes
            if route.get("role") == role
        )
        titles.extend(
            f"{route['route']} renders without framework errors"
            for route in shared_auth_routes
        )
    titles.extend(
        f"{route['route']} renders with seeded id substitutions"
        for route in dynamic_routes
    )
    return titles


def _inventory_report_titles(
    tests: list[summarize_local_auth_audit.AuditTest],
) -> collections.Counter[str]:
    return collections.Counter(
        test.title.split(" > ")[-1]
        for test in tests
        if Path(test.file).name == "local-auth-inventory.spec.ts"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--mongo-url", default=export_local_auth_inventory_env.DEFAULT_MONGO_URL
    )
    parser.add_argument(
        "--db-name", default=export_local_auth_inventory_env.DEFAULT_DB_NAME
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    check_local_auth_audit_readiness.assert_local_base_url(args.base_url)
    export_local_auth_inventory_env.assert_local_mongo_url(args.mongo_url)
    export_local_auth_inventory_env.assert_staging_db_name(args.db_name)

    manifest = audit_inventory_static_gaps.load_manifest(args.manifest)
    scale_issues = validate_scale_seed_safety.validate_plan(
        EXPECTED_SCALE_PLAN,
        parent_count=250,
        students_per_parent=2,
        months=list(scale_blno_staging.DEFAULT_MONTHS),
    )
    if scale_issues:
        raise SystemExit(
            "Scale safety validator failed for expected deterministic plan."
        )

    client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5_000)
    try:
        client.admin.command("ping")
        db = client[args.db_name]
        inventory = export_local_auth_inventory_env.build_inventory_env(db)
        cleanup_counts = scale_blno_staging.count_synthetic_scale_rows(db)
    finally:
        client.close()

    report_path = args.evidence_dir / "playwright-report.json"
    playwright_report = (
        summarize_local_auth_audit.load_report(report_path)
        if report_path.exists()
        else None
    )
    report = build_report(
        gate_items_from_state(
            manifest=manifest,
            base_url=args.base_url,
            evidence_dir=args.evidence_dir,
            inventory=inventory,
            cleanup_counts=cleanup_counts,
            report=playwright_report,
        )
    )
    rendered = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.format == "json"
        else render_markdown(report)
    )
    print(rendered)
    return 0 if report["result"] == "CLEAN_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
