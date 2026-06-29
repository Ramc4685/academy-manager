#!/usr/bin/env python3
"""Read-only readiness checks for the local-auth inventory audit."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pymongo import MongoClient

import export_local_auth_inventory_env
import scale_blno_staging
import summarize_local_auth_audit

DEFAULT_BASE_URL = os.environ.get("LOCAL_AUTH_BASE_URL", "http://blno.localhost:3000")
DEFAULT_EVIDENCE_DIR = Path(
    os.environ.get(
        "LOCAL_AUTH_EVIDENCE_DIR",
        "/tmp/academy-manager-local/evidence/20260628-production-scale-audit",
    )
)
REQUIRED_AUTH_ENV = (
    "LOCAL_AUTH_ADMIN_EMAIL",
    "LOCAL_AUTH_ADMIN_PASSWORD",
    "LOCAL_AUTH_COACH_EMAIL",
    "LOCAL_AUTH_COACH_PASSWORD",
    "LOCAL_AUTH_PARENT_EMAIL",
    "LOCAL_AUTH_PARENT_PASSWORD",
)
EXPECTED_SCALE_PLAN = scale_blno_staging.build_scale_plan(
    parent_count=250,
    students_per_parent=2,
    months=list(scale_blno_staging.DEFAULT_MONTHS),
)


@dataclass(frozen=True)
class ReadinessItem:
    status: str
    name: str
    detail: str


def assert_local_base_url(base_url: str) -> None:
    parsed = urllib.parse.urlparse(base_url)
    host = (parsed.hostname or "").lower()
    allowed_hosts = {"localhost", "127.0.0.1", "blno.localhost"}
    if parsed.scheme != "http" or host not in allowed_hosts:
        raise SystemExit(
            f"REFUSING: LOCAL_AUTH_BASE_URL must target local SaaS staging; "
            f"got {base_url!r}"
        )


def readiness_items_from_state(
    *,
    base_url: str,
    evidence_dir: Path,
    inventory: Any,
    cleanup_counts: dict[str, int],
    report: dict[str, Any] | None,
) -> list[ReadinessItem]:
    items = [
        ReadinessItem("ok", "base_url", f"Local base URL: {base_url}"),
        ReadinessItem("ok", "evidence_dir", str(evidence_dir)),
    ]
    items.append(auth_env_item())

    if inventory.missing:
        items.append(
            ReadinessItem(
                "block",
                "dynamic_route_ids",
                "Missing env vars: " + ", ".join(inventory.missing),
            )
        )
    else:
        items.append(
            ReadinessItem(
                "ok",
                "dynamic_route_ids",
                f"All {len(inventory.values)} dynamic route env vars available",
            )
        )

    items.append(scale_rows_item(cleanup_counts))

    if report is None:
        items.append(
            ReadinessItem(
                "warn",
                "playwright_report",
                "No Playwright JSON report found yet",
            )
        )
    else:
        tests = summarize_local_auth_audit.collect_tests(report)
        failed = [
            test
            for test in tests
            if test.status in {"failed", "timedOut", "interrupted"}
        ]
        skipped = [test for test in tests if test.status == "skipped"]
        items.append(
            ReadinessItem(
                "ok" if not failed else "warn",
                "playwright_report",
                f"Report has {len(tests)} tests, {len(failed)} failed, "
                f"{len(skipped)} skipped",
            )
        )

    return items


def auth_env_item(env: dict[str, str] | None = None) -> ReadinessItem:
    source = os.environ if env is None else env
    missing = [
        name for name in ("LOCAL_AUTH_E2E", *REQUIRED_AUTH_ENV) if not source.get(name)
    ]
    if source.get("LOCAL_AUTH_E2E") and source.get("LOCAL_AUTH_E2E") != "1":
        missing.append("LOCAL_AUTH_E2E=1")
    if missing:
        return ReadinessItem(
            "block",
            "auth_env",
            "Missing real-auth Playwright env: " + ", ".join(missing),
        )
    return ReadinessItem(
        "ok",
        "auth_env",
        "LOCAL_AUTH_E2E=1 and admin/coach/parent credentials are present.",
    )


def scale_rows_item(cleanup_counts: dict[str, int]) -> ReadinessItem:
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
        return ReadinessItem(
            "warn",
            "synthetic_scale_rows",
            "Synthetic production-scale rows are not fully applied: " + sample,
        )
    if extra:
        sample = ", ".join(
            f"{collection} extra {count}"
            for collection, count in list(extra.items())[:5]
        )
        return ReadinessItem(
            "warn",
            "synthetic_scale_rows",
            "Synthetic scale rows exceed expected deterministic counts: " + sample,
        )
    return ReadinessItem(
        "ok",
        "synthetic_scale_rows",
        "Expected 250-parent synthetic scale rows are present.",
    )


def render_markdown(items: list[ReadinessItem]) -> str:
    lines = ["# Local Auth Audit Readiness", ""]
    for item in items:
        lines.append(f"- {item.status.upper()} `{item.name}`: {item.detail}")
    blockers = [item for item in items if item.status == "block"]
    lines.extend(
        [
            "",
            f"Result: {'BLOCKED' if blockers else 'READY_WITH_WARNINGS' if _has_warnings(items) else 'READY'}",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--mongo-url", default=export_local_auth_inventory_env.DEFAULT_MONGO_URL
    )
    parser.add_argument(
        "--db-name", default=export_local_auth_inventory_env.DEFAULT_DB_NAME
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    assert_local_base_url(args.base_url)
    export_local_auth_inventory_env.assert_local_mongo_url(args.mongo_url)
    export_local_auth_inventory_env.assert_staging_db_name(args.db_name)

    client = MongoClient(args.mongo_url, serverSelectionTimeoutMS=5_000)
    try:
        client.admin.command("ping")
        db = client[args.db_name]
        inventory = export_local_auth_inventory_env.build_inventory_env(db)
        cleanup_counts = scale_blno_staging.count_synthetic_scale_rows(db)
    finally:
        client.close()

    report_path = args.evidence_dir / "playwright-report.json"
    report = (
        summarize_local_auth_audit.load_report(report_path)
        if report_path.exists()
        else None
    )
    items = readiness_items_from_state(
        base_url=args.base_url,
        evidence_dir=args.evidence_dir,
        inventory=inventory,
        cleanup_counts=cleanup_counts,
        report=report,
    )

    if args.format == "json":
        print(json.dumps([asdict(item) for item in items], indent=2))
    else:
        print(render_markdown(items))
    return 1 if any(item.status == "block" for item in items) else 0


def _has_warnings(items: list[ReadinessItem]) -> bool:
    return any(item.status == "warn" for item in items)


if __name__ == "__main__":
    raise SystemExit(main())
