#!/usr/bin/env python3
"""Summarize failed GitHub Actions runs for the PR feedback loop."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


ERROR_PATTERNS = (
    "##[error]",
    "Error:",
    "FAILED",
    "failed",
    "Traceback",
    "vulnerabilities found",
    "│ high",
    "│ Package",
    "│ Vulnerable versions",
    "│ Patched versions",
    "│ Paths",
    "│ More info",
    "Severity:",
    "Process completed with exit code",
)


@dataclass(frozen=True)
class FailedStep:
    job_name: str
    job_id: int
    step_name: str
    job_url: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a failed GitHub Actions run and print a compact self-healing handoff."
    )
    parser.add_argument(
        "run",
        nargs="?",
        help="GitHub Actions run id or URL. Defaults to the current branch PR's latest run.",
    )
    parser.add_argument(
        "--max-log-lines",
        type=int,
        default=18,
        help="Maximum matching log lines to include per failed job.",
    )
    args = parser.parse_args()

    run_id = extract_run_id(args.run) if args.run else latest_pr_run_id()
    if not run_id:
        print("No run id found. Pass a run URL/id or run this on a branch with a PR.", file=sys.stderr)
        return 2

    run = gh_json(["run", "view", run_id, "--json", "url,workflowName,conclusion,status,headBranch,headSha,jobs"])
    failed_steps = collect_failed_steps(run)

    print(f"# PR Failure Feedback")
    print(f"- Run: {run.get('url')}")
    print(f"- Workflow: {run.get('workflowName')}")
    print(f"- Branch: {run.get('headBranch')}")
    print(f"- SHA: {run.get('headSha')}")
    print(f"- Status: {run.get('status')} / {run.get('conclusion')}")
    print()

    if not failed_steps:
        print("No failed job steps found in this run.")
        return 0

    print("## Failed Steps")
    for step in failed_steps:
        print(f"- {step.job_name} -> {step.step_name}: {step.job_url}")
    print()

    print("## Evidence")
    for step in failed_steps:
        print(f"### {step.job_name} / {step.step_name}")
        for line in matching_log_lines(run_id, step.job_id, args.max_log_lines):
            print(line)
        print()

    print("## Local Self-Heal Loop")
    print("1. Reproduce the first failed step locally with the same command shown in the job log.")
    print("2. Fix the narrow cause and add or update regression coverage when practical.")
    print("3. Run the full local CI-equivalent block for the touched area.")
    print(
        "4. Update the relevant docs/test-results/active/ ledger with the failure cause, fix, verification, and skipped checks."
    )
    print("5. Push only after the local reproduction command is green.")
    return 1


def extract_run_id(value: str) -> str:
    match = re.search(r"/actions/runs/(\d+)", value)
    if match:
        return match.group(1)
    if value.isdigit():
        return value
    return value.strip()


def latest_pr_run_id() -> str | None:
    pr = gh_json(["pr", "view", "--json", "number"], check=False)
    if not pr or not pr.get("number"):
        return None
    checks = gh_json(
        [
            "pr",
            "checks",
            str(pr["number"]),
            "--json",
            "detailsUrl,completedAt,startedAt,state,bucket,name",
        ],
        check=False,
    )
    if not checks:
        return None
    for check in checks:
        run_id = extract_run_id(check.get("detailsUrl", ""))
        if run_id.isdigit():
            return run_id
    return None


def collect_failed_steps(run: dict[str, Any]) -> list[FailedStep]:
    failed: list[FailedStep] = []
    for job in run.get("jobs", []):
        if job.get("conclusion") != "failure":
            continue
        failed_job_steps = [
            step for step in job.get("steps", []) if step.get("conclusion") == "failure"
        ]
        if not failed_job_steps:
            failed.append(
                FailedStep(
                    job_name=job.get("name", "unknown job"),
                    job_id=int(job["databaseId"]),
                    step_name="job failed",
                    job_url=job.get("url", ""),
                )
            )
            continue
        for step in failed_job_steps:
            failed.append(
                FailedStep(
                    job_name=job.get("name", "unknown job"),
                    job_id=int(job["databaseId"]),
                    step_name=step.get("name", "unknown step"),
                    job_url=job.get("url", ""),
                )
            )
    return failed


def matching_log_lines(run_id: str, job_id: int, limit: int) -> list[str]:
    proc = run(["gh", "run", "view", run_id, "--job", str(job_id), "--log"], check=False)
    if proc.returncode != 0:
        return [f"(could not fetch job log: {proc.stderr.strip()})"]

    matches: list[str] = []
    for raw_line in proc.stdout.splitlines():
        message = raw_line.split("\t", 3)[-1].strip()
        if any(pattern in message for pattern in ERROR_PATTERNS):
            matches.append(message)
        if len(matches) >= limit:
            break
    if matches:
        return matches
    return ["(no matching error lines found; inspect full job log)"]


def gh_json(args: list[str], *, check: bool = True) -> Any:
    proc = run(["gh", *args], check=check)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)


def run(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    if check and proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    return proc


if __name__ == "__main__":
    raise SystemExit(main())
