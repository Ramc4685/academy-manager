#!/usr/bin/env python3
"""Summarize local-auth Playwright audit evidence.

Reads the JSON report written by frontend/playwright.local-auth.config.ts and
prints a compact Markdown summary for the active QA ledger or bug log triage.
This script is read-only unless --output is supplied.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_REPORT = Path(
    "/tmp/academy-manager-local/evidence/20260628-production-scale-audit/"
    "playwright-report.json"
)


@dataclass(frozen=True)
class AuditTest:
    title: str
    file: str
    project: str
    status: str
    annotations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)


def load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Report not found: {path}")
    return json.loads(path.read_text())


def collect_tests(report: dict[str, Any]) -> list[AuditTest]:
    tests: list[AuditTest] = []
    for suite in report.get("suites", []):
        _collect_suite_tests(suite, [], tests)
    return tests


def render_markdown(report: dict[str, Any], tests: list[AuditTest]) -> str:
    stats = report.get("stats", {})
    counts = _status_counts(tests)
    failed = [
        test for test in tests if test.status in {"failed", "timedOut", "interrupted"}
    ]
    skipped = [test for test in tests if test.status == "skipped"]

    lines = [
        "# Local Auth Audit Evidence Summary",
        "",
        f"- Started: {stats.get('startTime', 'unknown')}",
        f"- Duration ms: {stats.get('duration', 'unknown')}",
        f"- Total tests: {len(tests)}",
        f"- Passed: {counts.get('passed', 0)}",
        f"- Failed: {len(failed)}",
        f"- Skipped: {len(skipped)}",
        f"- Flaky: {stats.get('flaky', 0)}",
        "",
    ]

    if failed:
        lines.extend(["## Failed Workflows", ""])
        for index, test in enumerate(failed, start=1):
            lines.extend(
                [
                    f"### BUG-CANDIDATE-{index:03d}: {test.title}",
                    "",
                    f"- File: {test.file}",
                    f"- Project: {test.project}",
                    f"- Status: {test.status}",
                    "- Errors:",
                ]
            )
            lines.extend(
                f"  - {error}" for error in test.errors or ["No error text recorded"]
            )
            lines.append("- Evidence:")
            lines.extend(
                f"  - {attachment}"
                for attachment in test.attachments
                or ["No screenshot/trace/video attachment recorded"]
            )
            lines.append("")
    else:
        lines.extend(["## Failed Workflows", "", "None recorded in this report.", ""])

    if skipped:
        lines.extend(["## Skipped Or Blocked Workflows", ""])
        for test in skipped:
            reason = (
                "; ".join(test.annotations)
                if test.annotations
                else "No skip reason recorded"
            )
            lines.append(f"- {test.title} ({test.file}): {reason}")
        lines.append("")

    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = load_report(args.report)
    summary = render_markdown(report, collect_tests(report))
    if args.output:
        args.output.write_text(summary + "\n")
    else:
        print(summary)
    return 0


def _collect_suite_tests(
    suite: dict[str, Any], title_path: list[str], tests: list[AuditTest]
) -> None:
    current_path = [*title_path, suite.get("title", "")]
    for spec in suite.get("specs", []):
        spec_title = spec.get("title", "Untitled workflow")
        for test in spec.get("tests", []):
            tests.append(
                _audit_test_from_report_test(spec, test, current_path, spec_title)
            )
    for child in suite.get("suites", []):
        _collect_suite_tests(child, current_path, tests)


def _audit_test_from_report_test(
    spec: dict[str, Any],
    test: dict[str, Any],
    suite_path: list[str],
    spec_title: str,
) -> AuditTest:
    results = test.get("results", [])
    last_result = results[-1] if results else {}
    attachments = [
        str(attachment.get("path") or attachment.get("name"))
        for result in results
        for attachment in result.get("attachments", [])
        if attachment.get("path") or attachment.get("name")
    ]
    errors = [
        str(error.get("message") or error.get("value"))
        for result in results
        for error in result.get("errors", [])
        if error.get("message") or error.get("value")
    ]
    annotations = [
        str(annotation.get("description") or annotation.get("type"))
        for annotation in test.get("annotations", [])
        if annotation.get("description") or annotation.get("type")
    ]
    title = " > ".join(part for part in [*suite_path, spec_title] if part)
    return AuditTest(
        title=title,
        file=str(spec.get("file", "")),
        project=str(test.get("projectName", "")),
        status=str(last_result.get("status") or test.get("status") or "unknown"),
        annotations=annotations,
        errors=errors,
        attachments=attachments,
    )


def _status_counts(tests: list[AuditTest]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for test in tests:
        counts[test.status] = counts.get(test.status, 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
